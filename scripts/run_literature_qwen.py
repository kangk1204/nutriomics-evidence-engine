"""Pinned Qwen inference only on scoped chemical-gene co-mention documents.

This is a separate frozen run. It never changes the ongoing DrugProt runner,
uses no relation gold, and reports no food precision or clinical efficacy.
"""
import argparse
import hashlib
import json
import platform
import time
from pathlib import Path
from run_qwen import verify_model, messages_with_sentence_offsets, digest, save, now, MODEL
from nutriomics_evidence.literature import load_prepared, analyze_literature
import nutriomics_evidence.literature as literature_module
import nutriomics_evidence.extraction as extraction_module


def infer(args):
    documents, preparation = load_prepared(args.prepared)
    lock = verify_model(args.model_dir, args.model_lock)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    eligible = [document for document in documents if document["qwen_eligible"]]
    # The prompt contains original text and candidate mentions, not previous
    # rule/model outputs, hidden clinical labels or inferred gene outcomes.
    prompts = {document["pmid"]: messages_with_sentence_offsets({key: document[key] for key in ("pmid", "text", "entities")})
               for document in eligible}
    prompt_hash = hashlib.sha256(json.dumps(prompts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    config = {"model": MODEL, "commit": lock["commit"], "model_lock_sha256": digest(args.model_lock),
              "preparation_lock_sha256": digest(args.prepared / "preparation_lock.json"),
              "documents_sha256": preparation["files"]["documents.jsonl"], "prompt_sha256": prompt_hash,
              "script_sha256": digest(__file__), "helper_script_sha256": digest(Path(__file__).with_name("run_qwen.py")),
              "literature_module_sha256": digest(literature_module.__file__),
              "extraction_module_sha256": digest(extraction_module.__file__),
              "batch_size": args.batch_size, "max_new_tokens": args.max_new_tokens,
              "max_input_tokens": args.max_input_tokens, "seed": 42, "do_sample": False,
              "quantization": "bitsandbytes NF4 4bit double quantization, BF16 computation",
              "documents": len(documents), "eligible_documents": len(eligible),
              "selection": "All frozen1198 documents retained; infer only dictionary chemical-gene document co-mentions; others explicit empty abstentions",
              "gold_available": False, "batch_policy": "prespecified operational throughput setting; no gold-metric selection"}
    frozen = out / "inference_lock.json"
    if frozen.exists():
        if json.loads(frozen.read_text(encoding="utf-8")) != config:
            raise ValueError("Frozen literature inference config changed; use a new versioned directory")
    else:
        save(frozen, config)
    responses = {}
    path = out / "responses.jsonl"
    cohort = {document["pmid"] for document in documents}
    if path.exists():
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                if row["pmid"] not in cohort or row["pmid"] in responses:
                    raise ValueError("Duplicate/out-of-cohort saved literature response")
                responses[row["pmid"]] = row
    # Record a real empty abstention for every unscoped/non-co-mentioned record.
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        for document in documents:
            if not document["qwen_eligible"] and document["pmid"] not in responses:
                row = {"pmid": document["pmid"], "status": "no_comention_abstention", "response": '{"relations": []}',
                       "reason": document["abstention_reason"], "model_invoked": False}
                responses[row["pmid"]] = row
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    todo = [document for document in eligible if document["pmid"] not in responses]
    started = time.monotonic()
    runtime = {"python": platform.python_version()}
    if todo:
        from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
        import transformers
        import torch
        import bitsandbytes
        if not torch.cuda.is_available():
            raise RuntimeError("Literature Qwen inference requires the authorized CUDA GPU")
        free, _ = torch.cuda.mem_get_info()
        if free < 8 * 1024**3:
            raise RuntimeError("Wait until the DrugProt run/coordinator releases the GPU")
        torch.manual_seed(42)
        tokenizer = AutoTokenizer.from_pretrained(args.model_dir, local_files_only=True, trust_remote_code=False, padding_side="left")
        if tokenizer.pad_token_id is None:
            tokenizer.pad_token = tokenizer.eos_token
        quantization = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.bfloat16,
                                         bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True)
        model = AutoModelForCausalLM.from_pretrained(args.model_dir, local_files_only=True, trust_remote_code=False,
                    quantization_config=quantization, device_map={"": 0}, torch_dtype=torch.bfloat16, attn_implementation="sdpa")
        model.eval()
        runtime.update(torch=torch.__version__, cuda=torch.version.cuda, gpu=torch.cuda.get_device_name(0),
                       transformers=transformers.__version__, bitsandbytes=bitsandbytes.__version__)
        with path.open("a", encoding="utf-8", newline="\n") as stream, (out / "batching_diagnostics.jsonl").open("a", encoding="utf-8", newline="\n") as diagnostics:
            for position in range(0, len(todo), args.batch_size):
                batch = todo[position:position + args.batch_size]
                texts = [tokenizer.apply_chat_template(prompts[document["pmid"]], tokenize=False, add_generation_prompt=True) for document in batch]
                lengths = [len(tokenizer.encode(text, add_special_tokens=False)) for text in texts]
                valid = [(document, text, length) for document, text, length in zip(batch, texts, lengths) if length <= args.max_input_tokens]
                rows = [{"pmid": document["pmid"], "status": "context_overflow", "response": "", "prompt_tokens": length}
                        for document, length in zip(batch, lengths) if length > args.max_input_tokens]
                batch_start = time.monotonic()
                if valid:
                    encoded = tokenizer([text for _, text, _ in valid], padding=True, return_tensors="pt", add_special_tokens=False).to("cuda")
                    try:
                        with torch.inference_mode():
                            output = model.generate(**encoded, max_new_tokens=args.max_new_tokens, do_sample=False,
                                        pad_token_id=tokenizer.pad_token_id, eos_token_id=tokenizer.eos_token_id)
                        generated = output[:, encoded.input_ids.shape[1]:]
                        for (document, _, length), tokens in zip(valid, generated):
                            count = int(tokens.ne(tokenizer.pad_token_id).sum())
                            rows.append({"pmid": document["pmid"], "status": "generated", "response": tokenizer.decode(tokens, skip_special_tokens=True),
                                         "prompt_tokens": length, "generated_tokens": count, "hit_output_limit": count >= args.max_new_tokens})
                    except (RuntimeError, ValueError) as error:
                        if isinstance(error, torch.OutOfMemoryError):
                            torch.cuda.empty_cache()
                        rows.extend({"pmid": document["pmid"], "status": "generation_error", "response": "",
                                     "error": str(error), "prompt_tokens": length} for document, _, length in valid)
                for row in rows:
                    responses[row["pmid"]] = row
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                stream.flush()
                elapsed = time.monotonic() - batch_start
                diagnostics.write(json.dumps({"batch_pmids": [document["pmid"] for document in batch], "prompt_tokens": lengths,
                      "elapsed_seconds": elapsed, "generated_tokens": sum(row.get("generated_tokens", 0) for row in rows),
                      "gpu_allocated_bytes": torch.cuda.memory_allocated(), "gpu_reserved_bytes": torch.cuda.memory_reserved(),
                      "statuses": [row["status"] for row in rows]}) + "\n")
                diagnostics.flush()
                complete = sum(pmid in responses for pmid in prompts)
                print(f"eligible documents {complete}/{len(eligible)}; total ledger {len(responses)}/{len(documents)}; elapsed {time.monotonic() - started:.1f}s", flush=True)
        del model
        torch.cuda.empty_cache()
    summary = analyze_literature(documents, responses, out)
    summary.update(completed_utc=now(), elapsed_this_invocation_seconds=time.monotonic() - started,
                   inference_lock_sha256=digest(frozen), responses_sha256=digest(path), runtime=runtime,
                   output_limit_documents=sum(bool(row.get("hit_output_limit")) for row in responses.values()))
    save(out / "inference_summary.json", summary)
    metadata_out = Path(__file__).resolve().parents[1] / "docs/literature"
    save(metadata_out / "inference_summary.json", summary)
    save(metadata_out / "inference_lock.json", config)
    status_path = metadata_out / "implementation_status.json"
    if status_path.exists():
        status = json.loads(status_path.read_text(encoding="utf-8"))
        status.update(status="actual_literature_inference_complete", completed_utc=summary["completed_utc"],
                      eligible_documents=len(eligible), total_response_records=len(responses),
                      accepted_extracted_candidate_rows=summary["accepted_relation_rows"],
                      food_domain_precision=None, gold_available=False,
                      inference_summary_sha256=digest(out / "inference_summary.json"))
        save(status_path, status)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--model-lock", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--max-new-tokens", type=int, default=1024)
    parser.add_argument("--max-input-tokens", type=int, default=8192)
    args = parser.parse_args()
    if args.batch_size < 1 or args.max_new_tokens < 1 or args.max_input_tokens < 1:
        parser.error("Batch and token limits must be positive")
    print(json.dumps(infer(args), indent=2))
