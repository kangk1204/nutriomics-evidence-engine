"""Read-only checkpoint continuation: original batch4 + remaining batch8.

No original artifact is rewritten. Scores are computed only after an exact
750-PMID merge; batching can change floating-point behavior and output text.
"""
import argparse
import hashlib
import json
import platform
import time
from pathlib import Path
from run_qwen import MODEL, verify_model, messages_with_sentence_offsets, analyze_responses, digest, save, now
import nutriomics_evidence.extraction as extraction_module

NEW_BATCH = 8
QUANTIZATION = "bitsandbytes NF4 4bit double quantization, BF16 computation"
STATUSES = {"generated", "context_overflow", "generation_error"}


def read_responses(path, cohort):
    """Read physical LF records, preserving legal U+2028/U+2029 string content."""
    path = Path(path)
    if not path.exists():
        return {}
    # Refuse a potentially interrupted last JSONL write instead of repairing it.
    with path.open("rb") as stream:
        stream.seek(0, 2)
        if stream.tell():
            stream.seek(-1, 2)
            if stream.read(1) != b"\n":
                raise ValueError("Response JSONL must end at a complete LF record")
    rows = {}
    with path.open(encoding="utf-8", newline="") as stream:
        for line in stream:
            row = json.loads(line)
            if not isinstance(row, dict) or row.get("pmid") not in cohort or row["pmid"] in rows:
                raise ValueError("Duplicate or unexpected response PMID")
            if row.get("status") not in STATUSES or not isinstance(row.get("response"), str):
                raise ValueError("Malformed response status/text")
            rows[row["pmid"]] = row
    return rows


def merge_responses(original, residual, cohort, require_complete=True):
    if set(original) & set(residual):
        raise ValueError("Original/continuation PMID overlap")
    merged = {**original, **residual}
    if set(merged) - set(cohort):
        raise ValueError("Merged responses contain unexpected PMID")
    if require_complete and set(merged) != set(cohort):
        raise ValueError("Merged responses do not cover the exact cohort")
    return merged


def assert_original_unchanged(args, snapshot):
    for name, expected in snapshot.items():
        path = args.original_out / name
        if digest(path) != expected:
            raise ValueError("Original artifact changed during continuation: " + name)


def assert_continuation_locks_unchanged(directory, snapshot):
    for name, expected in snapshot.items():
        if digest(Path(directory) / name) != expected:
            raise ValueError("Frozen continuation artifact changed: " + name)


def validate_checkpoint(args, documents, prompts, model_lock):
    original = args.original_out.resolve()
    out = args.out.resolve()
    if original == out or original in out.parents or out in original.parents:
        raise ValueError("Continuation output must be a separate directory from original artifacts")
    if len(documents) != 750 or len({document["pmid"] for document in documents}) != 750:
        raise ValueError("Exactly 750 distinct official development documents required")
    lock_path = original / "inference_lock.json"
    response_path = original / "responses.jsonl"
    if not lock_path.exists() or not response_path.exists():
        raise ValueError("Original lock and safely flushed response checkpoint required")
    if (original / "qwen_metrics.json").exists() or (original / "rule_metrics.json").exists():
        raise ValueError("Operational amendment must precede original cohort score artifacts")
    snapshot = {"inference_lock.json": digest(lock_path), "responses.jsonl": digest(response_path)}
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    prompt_sha = hashlib.sha256(json.dumps(prompts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    expected = {"repo_id": MODEL, "commit": model_lock["commit"], "model_lock_sha256": digest(args.model_lock),
                "abstracts_sha256": digest(args.abstracts), "entities_sha256": digest(args.entities),
                "gold_sha256": digest(args.gold) if args.gold else None, "prompt_sha256": prompt_sha,
                "script_sha256": digest(Path(__file__).with_name("run_qwen.py")),
                "batch_size": 4, "max_new_tokens": 1024, "max_input_tokens": 8192,
                "do_sample": False, "seed": 42, "quantization": QUANTIZATION, "no_finetuning": True,
                "prompt_policy": "unchanged existing schema prompt plus exact sentence candidates/offsets",
                "selection": "all 750 dev documents; errors remain abstentions; prompts never include gold relations"}
    for key, value in expected.items():
        if lock.get(key) != value:
            raise ValueError("Original model/prompt/source/settings hash mismatch: " + key)
    cohort = [document["pmid"] for document in documents]
    responses = read_responses(response_path, set(cohort))
    if not responses or len(responses) >= 750:
        raise ValueError("A nonempty partial original checkpoint is required")
    # A completed original batch can reorder overflow records, but its PMID set
    # must still be the first N source documents and N must be a whole batch4.
    if len(responses) % 4 or set(responses) != set(cohort[:len(responses)]):
        raise ValueError("Original checkpoint is not a complete flushed source-order batch4 prefix")
    assert_original_unchanged(args, snapshot)
    pending = [pmid for pmid in cohort if pmid not in responses]
    return lock, snapshot, responses, pending


def kv_budget(model_dir, batch=NEW_BATCH, input_tokens=8192, output_tokens=1024):
    config = json.loads((Path(model_dir) / "config.json").read_text(encoding="utf-8"))
    layers, heads, kv_heads, hidden = (int(config[key]) for key in
                                    ("num_hidden_layers", "num_attention_heads", "num_key_value_heads", "hidden_size"))
    if min(layers, heads, kv_heads, hidden) < 1 or hidden % heads:
        raise ValueError("Invalid pinned model attention dimensions")
    per_token = 2 * layers * kv_heads * (hidden // heads) * 2
    cache = per_token * batch * (input_tokens + output_tokens)
    return {"model_config_sha256": digest(Path(model_dir) / "config.json"), "layers": layers,
            "kv_heads": kv_heads, "head_dimension": hidden // heads, "bf16_bytes_per_token_document": per_token,
            "batch_size": batch, "worst_padded_input_plus_output_tokens": input_tokens + output_tokens,
            "worst_bf16_kv_bytes": cache, "workspace_reserve_bytes": int(1.5 * 1024**3),
            "preload_parameter_budget_bytes": 6 * 1024**3,
            "interpretation": "KV lower-bound estimate; NF4 weight budget and workspace reserve are operational assumptions, not a proof against all activation/prefill allocation peaks"}


def continuation(args):
    model_lock = verify_model(args.model_dir, args.model_lock)
    documents = extraction_module.load_drugprot(args.abstracts, args.entities)
    prompts = {document["pmid"]: messages_with_sentence_offsets(document) for document in documents}
    original_lock, snapshot, original, pending = validate_checkpoint(args, documents, prompts, model_lock)
    budget = kv_budget(args.model_dir)
    config = {"protocol": "DrugProt operational batching continuation v1", "original_artifact_sha256": snapshot,
              "original_inference_config": original_lock, "original_document_count": len(original),
              "original_pmids": [document["pmid"] for document in documents if document["pmid"] in original],
              "continuation_pmids_in_source_order": pending, "continuation_document_count": len(pending),
              "batch_size": NEW_BATCH, "original_batch_size": 4, "seed": 42,
              "seed_policy": "torch.manual_seed(42) once per process start; no per-batch reseeding, matching original policy",
              "script_sha256": digest(__file__), "original_helper_sha256": digest(Path(__file__).with_name("run_qwen.py")),
              "extraction_module_sha256": digest(extraction_module.__file__),
              "model_lock_sha256": digest(args.model_lock), "commit": model_lock["commit"],
              "prompt_sha256": original_lock["prompt_sha256"], "max_input_tokens": 8192, "max_new_tokens": 1024,
              "do_sample": False, "quantization": QUANTIZATION, "no_finetuning": True,
              "memory_review": budget,
              "amendment_basis": "Throughput and 16GB GPU memory review, before full-cohort Qwen scoring; no score-based tuning",
              "score_artifacts_read_for_selection": False,
              "output_parity_claim": False,
              "numerical_note": "Different batch shapes and process restart can change floating-point calculations and generated text despite greedy decoding"}
    args.out.mkdir(parents=True, exist_ok=True)
    lock_path = args.out / "continuation_lock.json"
    if lock_path.exists():
        if json.loads(lock_path.read_text(encoding="utf-8")) != config:
            raise ValueError("Immutable continuation settings/checkpoint changed; choose a new directory")
    else:
        if any(args.out.iterdir()):
            raise ValueError("Fresh continuation directory required unless its immutable lock exists")
        save(lock_path, config)
        save(args.out / "operational_amendment.json", {"recorded_utc": now(), "continuation_lock_sha256": digest(lock_path), **config})
    amendment_path = args.out / "operational_amendment.json"
    amendment = json.loads(amendment_path.read_text(encoding="utf-8"))
    if amendment.get("continuation_lock_sha256") != digest(lock_path):
        raise ValueError("Operational amendment's continuation lock hash changed")
    if {key: value for key, value in amendment.items() if key not in {"recorded_utc", "continuation_lock_sha256"}} != config:
        raise ValueError("Operational amendment differs from the frozen continuation lock")
    continuation_seal = {name: digest(args.out / name) for name in ("continuation_lock.json", "operational_amendment.json")}
    residual_path = args.out / "residual_responses.jsonl"
    residual = read_responses(residual_path, set(pending))
    if set(residual) != set(pending[:len(residual)]) or (len(residual) < len(pending) and len(residual) % NEW_BATCH):
        raise ValueError("Residual checkpoint is not a complete flushed source-order batch8 prefix")
    merge_responses(original, residual, [document["pmid"] for document in documents], require_complete=False)
    todo = [document for document in documents if document["pmid"] in pending and document["pmid"] not in residual]
    started = time.monotonic()
    runtime = {"python": platform.python_version()}
    if todo:
        from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
        import transformers
        import torch
        import bitsandbytes
        if not torch.cuda.is_available():
            raise RuntimeError("Authorized CUDA GPU required")
        free, total = torch.cuda.mem_get_info()
        before = {**budget, "free_before_model_bytes": free, "device_total_bytes": total,
                  "gpu": torch.cuda.get_device_name(0)}
        save(args.out / "gpu_preflight.json", before)
        if free < budget["worst_bf16_kv_bytes"] + budget["preload_parameter_budget_bytes"] + budget["workspace_reserve_bytes"]:
            raise RuntimeError("GPU memory below batch8 reviewed preload budget; wait for original process to exit")
        torch.manual_seed(42)
        tokenizer = AutoTokenizer.from_pretrained(args.model_dir, local_files_only=True, trust_remote_code=False, padding_side="left")
        if tokenizer.pad_token_id is None:
            tokenizer.pad_token = tokenizer.eos_token
        quantization = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.bfloat16,
                                         bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True)
        model = AutoModelForCausalLM.from_pretrained(args.model_dir, local_files_only=True, trust_remote_code=False,
                    quantization_config=quantization, device_map={"": 0}, torch_dtype=torch.bfloat16, attn_implementation="sdpa")
        model.eval()
        free, _ = torch.cuda.mem_get_info()
        before.update(free_after_model_bytes=free, allocated_after_model_bytes=torch.cuda.memory_allocated(),
                      reserved_after_model_bytes=torch.cuda.memory_reserved())
        save(args.out / "gpu_preflight.json", before)
        if free < budget["worst_bf16_kv_bytes"] + budget["workspace_reserve_bytes"]:
            raise RuntimeError("GPU memory below reviewed batch8 KV/workspace reserve after model loading")
        runtime.update(torch=torch.__version__, cuda=torch.version.cuda, gpu=torch.cuda.get_device_name(0),
                       transformers=transformers.__version__, bitsandbytes=bitsandbytes.__version__)
        with residual_path.open("a", encoding="utf-8", newline="\n") as stream, (args.out / "batch_ledger.jsonl").open("a", encoding="utf-8", newline="\n") as ledger:
            for position in range(0, len(todo), NEW_BATCH):
                assert_original_unchanged(args, snapshot)
                assert_continuation_locks_unchanged(args.out, continuation_seal)
                batch = todo[position:position + NEW_BATCH]
                texts = [tokenizer.apply_chat_template(prompts[document["pmid"]], tokenize=False, add_generation_prompt=True) for document in batch]
                lengths = [len(tokenizer.encode(text, add_special_tokens=False)) for text in texts]
                valid = [(document, text, length) for document, text, length in zip(batch, texts, lengths) if length <= 8192]
                records = [{"pmid": document["pmid"], "status": "context_overflow", "response": "", "prompt_tokens": length}
                           for document, length in zip(batch, lengths) if length > 8192]
                batch_started = time.monotonic()
                if valid:
                    try:
                        encoded = tokenizer([text for _, text, _ in valid], padding=True, return_tensors="pt", add_special_tokens=False).to("cuda")
                        with torch.inference_mode():
                            output = model.generate(**encoded, max_new_tokens=1024, do_sample=False,
                                    pad_token_id=tokenizer.pad_token_id, eos_token_id=tokenizer.eos_token_id)
                        generated = output[:, encoded.input_ids.shape[1]:]
                        for (document, _, length), tokens in zip(valid, generated):
                            count = int(tokens.ne(tokenizer.pad_token_id).sum())
                            records.append({"pmid": document["pmid"], "status": "generated", "response": tokenizer.decode(tokens, skip_special_tokens=True),
                                            "prompt_tokens": length, "generated_tokens": count, "hit_output_limit": count >= 1024})
                    except (RuntimeError, ValueError) as error:
                        if isinstance(error, torch.OutOfMemoryError):
                            torch.cuda.empty_cache()
                        records.extend({"pmid": document["pmid"], "status": "generation_error", "response": "",
                                        "error": str(error), "prompt_tokens": length} for document, _, length in valid)
                if len(records) != len(batch) or {row["pmid"] for row in records} != {document["pmid"] for document in batch}:
                    raise ValueError("Each scheduled batch document requires exactly one response/abstention")
                for row in records:
                    if row["pmid"] in residual:
                        raise ValueError("Duplicate residual response")
                    residual[row["pmid"]] = row
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                stream.flush()
                ledger.write(json.dumps({"recorded_utc": now(), "scheduled_pmids_in_source_order": [document["pmid"] for document in batch],
                       "process_start_seed": 42, "per_batch_reseed": False, "batch_size_limit": NEW_BATCH,
                       "prompt_tokens": lengths, "elapsed_seconds": time.monotonic() - batch_started,
                       "generated_tokens": sum(row.get("generated_tokens", 0) for row in records),
                       "statuses": [row["status"] for row in records], "gpu_allocated_bytes": torch.cuda.memory_allocated(),
                       "gpu_reserved_bytes": torch.cuda.memory_reserved()}) + "\n")
                ledger.flush()
                print(f"total documents {len(original) + len(residual)}/750; original4={len(original)} remaining8={len(residual)}/{len(pending)} elapsed {time.monotonic() - started:.1f}s", flush=True)
        del model
        torch.cuda.empty_cache()
    assert_original_unchanged(args, snapshot)
    assert_continuation_locks_unchanged(args.out, continuation_seal)
    # Re-read persisted rows rather than trusting only the in-memory dictionary.
    residual = read_responses(residual_path, set(pending))
    cohort = [document["pmid"] for document in documents]
    merged = merge_responses(original, residual, cohort, require_complete=True)
    merged_path = args.out / "merged_responses.jsonl"
    with merged_path.open("w", encoding="utf-8", newline="\n") as stream:
        for pmid in cohort:
            stream.write(json.dumps(merged[pmid], ensure_ascii=False) + "\n")
    coverage = {"expected_documents": 750, "response_documents": len(merged), "duplicate_pmids": 0,
                "unexpected_pmids": 0, "missing_pmids": 0, "original_documents": len(original),
                "continuation_documents": len(residual), "original_artifacts_unchanged": True,
                "ordered_pmids_sha256": hashlib.sha256(json.dumps(cohort).encode()).hexdigest()}
    save(args.out / "coverage_audit.json", coverage)
    # First relation scoring occurs only after the complete merged coverage gate.
    summary = analyze_responses(documents, merged, args.out, args.gold, args.abstracts, args.entities)
    summary.update(completed_utc=now(), elapsed_this_invocation_seconds=time.monotonic() - started,
                   responses_sha256=digest(merged_path), coverage_audit=coverage, runtime=runtime,
                   generated_output_limit_documents=sum(bool(row.get("hit_output_limit")) for row in merged.values()),
                   continuation_lock_sha256=digest(lock_path), operational_amendment_sha256=digest(amendment_path),
                   execution_protocols=[{"protocol": "original", "batch_size": 4, "document_count": len(original),
                       "script_sha256": original_lock["script_sha256"], "inference_lock_sha256": snapshot["inference_lock.json"],
                       "responses_sha256": snapshot["responses.jsonl"], "seed": 42},
                       {"protocol": "continuation", "batch_size": NEW_BATCH, "document_count": len(residual),
                       "script_sha256": config["script_sha256"], "inference_lock_sha256": digest(lock_path),
                       "responses_sha256": digest(residual_path), "seed": 42, "per_batch_reseed": False}],
                   operational_interpretation="One full750 cohort scored after an unscored throughput amendment; mixed batch4/batch8 execution, no output parity or score-based tuning claim",
                   contamination_note="Public DrugProt/PubMed may occur in pretraining; no guarantee of unseen pretraining documents")
    save(args.out / "inference_summary.json", summary)
    assert_original_unchanged(args, snapshot)
    assert_continuation_locks_unchanged(args.out, continuation_seal)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original-out", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--model-lock", type=Path, required=True)
    parser.add_argument("--abstracts", type=Path, required=True)
    parser.add_argument("--entities", type=Path, required=True)
    parser.add_argument("--gold", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    print(json.dumps(continuation(parser.parse_args()), indent=2))
