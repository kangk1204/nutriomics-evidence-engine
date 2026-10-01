"""Pinned official Qwen2.5-7B-Instruct 4-bit inference on held DrugProt dev.

No finetuning, gold relations in prompts, offset repair, or score-based tuning.
Failures are retained as abstentions in the full-cohort evaluation.
"""
import argparse
import hashlib
import json
import os
import platform
import re
import time
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path

MODEL = "Qwen/Qwen2.5-7B-Instruct"


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    hasher = hashlib.sha256()
    with open(path,"rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""):
            hasher.update(block)
    return hasher.hexdigest()


def save(path,payload):
    path = Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(payload,indent=2,ensure_ascii=False,allow_nan=False),encoding="utf-8")


def download_model(model_dir,lock_path,revision="main"):
    from huggingface_hub import HfApi,snapshot_download
    model_dir,lock_path = Path(model_dir),Path(lock_path)
    if lock_path.exists():
        lock = json.loads(lock_path.read_text())
        if lock["repo_id"]!=MODEL:
            raise ValueError("Model lock is for a different repository")
        # Preserve the exact source lock across reruns; changing its timestamp
        # would invalidate otherwise identical resumable inference metadata.
        return verify_model(model_dir,lock_path)
    else:
        info = HfApi().model_info(MODEL,revision=revision)
        commit = info.sha
        if not re.fullmatch(r"[a-f0-9]{40}",commit):
            raise ValueError("Model API did not resolve an immutable commit")
    snapshot_download(repo_id=MODEL,revision=commit,local_dir=model_dir,max_workers=4,
                      allow_patterns=["*.safetensors","*.json","*.txt","tokenizer*","merges.txt","vocab.json","LICENSE","README.md"])
    files = []
    for path in sorted(model_dir.rglob("*")):
        if path.is_file() and ".cache" not in path.parts:
            files.append({"path":path.relative_to(model_dir).as_posix(),"bytes":path.stat().st_size,"sha256":digest(path)})
    if not any(row["path"].endswith(".safetensors") for row in files):
        raise ValueError("No official model weights downloaded")
    lock = {"repo_id":MODEL,"commit":commit,"resolved_from_revision":revision,"downloaded_utc":now(),
            "official_url":"https://huggingface.co/Qwen/Qwen2.5-7B-Instruct","license":"Apache-2.0 per official model card; LICENSE retained",
            "files":files,"total_bytes":sum(row["bytes"] for row in files),"trust_remote_code":False}
    save(lock_path,lock)
    return lock


def verify_model(model_dir,lock_path):
    lock = json.loads(Path(lock_path).read_text())
    if lock["repo_id"]!=MODEL or not re.fullmatch(r"[a-f0-9]{40}",lock["commit"]):
        raise ValueError("Invalid pinned official model lock")
    for row in lock["files"]:
        path = Path(model_dir)/row["path"]
        if path.stat().st_size!=row["bytes"] or digest(path)!=row["sha256"]:
            raise ValueError(f"Model file changed: {row['path']}")
    return lock


def messages_with_sentence_offsets(document):
    from nutriomics_evidence.extraction import qwen_prompt,sentence_spans
    enriched = dict(document)
    enriched["sentence_candidates"] = [{"text":document["text"][start:end],"start":start,"end":end,
                                        "entity_ids":[entity["id"] for entity in document["entities"] if start<=entity["start"] and entity["end"]<=end]}
                                       for start,end in sentence_spans(document["text"])]
    # Supply exact offsets so the LM need not count characters. The validator is unchanged.
    return qwen_prompt(enriched)


def analyze_responses(documents,responses,out,gold,abstracts,entities):
    from nutriomics_evidence.extraction import parse_qwen,write_relations,evaluate,rule_extract
    reports,relations = [],[]
    reasons = Counter()
    statuses = Counter()
    for document in documents:
        response = responses.get(document["pmid"])
        if response is None:
            statuses["missing_response"] += 1
            reports.append({"pmid":document["pmid"],"accepted":[],"rejected":[],"error":"missing_response"})
            continue
        statuses[response["status"]] += 1
        try:
            parsed = parse_qwen(response["response"],document)
            relations.extend(parsed["accepted"])
            for rejection in parsed["rejected"]:
                reasons.update(rejection["reasons"])
        except (ValueError,TypeError,KeyError) as error:
            reasons["invalid_json_or_top_level_schema"] += 1
            parsed = {"pmid":document["pmid"],"accepted":[],"rejected":[],"error":str(error)}
        reports.append(parsed)
    write_relations(out/"qwen_relations.tsv",relations)
    rule_relations = [relation for document in documents for relation in rule_extract(document)]
    write_relations(out/"rule_relations.tsv",rule_relations)
    save(out/"validation_reports.json",reports)
    if gold is not None:
        score = evaluate(gold,out/"qwen_relations.tsv",documents)
        rule_score = evaluate(gold,out/"rule_relations.tsv",documents)
        save(out/"qwen_metrics.json",score)
        save(out/"rule_metrics.json",rule_score)
    else:
        score,rule_score = None,None
    result = {"documents":len(documents),"response_status_counts":dict(statuses),"rejection_reason_counts":dict(reasons),
              "accepted_relations":len(relations),"rejected_relation_rows":sum(len(row["rejected"]) for row in reports),
              "json_or_top_schema_error_documents":reasons["invalid_json_or_top_level_schema"],
              "qwen_micro":score["micro"] if score else None,"rule_micro":rule_score["micro"] if rule_score else None,
              "gold_mentions_used":True,"semantic_entailment_validated":False,
              "scope":"held development relation extraction with provided gold mentions; no NER/food-domain/external-pretraining independence claim",
              "offset_policy":"exact original substring and offsets; no automatic offset repair; negation flagged/rejected",
              "official_evaluator":"https://github.com/tonifuc3m/drugprot-evaluation-library"}
    save(out/"inference_summary.json",result)
    return result


def infer(args):
    lock = verify_model(args.model_dir,args.model_lock)
    from nutriomics_evidence.extraction import load_drugprot
    from transformers import AutoTokenizer,AutoModelForCausalLM,BitsAndBytesConfig
    import transformers
    import torch
    import bitsandbytes
    documents = load_drugprot(args.abstracts,args.entities)
    if len(documents)!=750:
        raise ValueError("Primary inference requires the pinned 750-document official development cohort")
    out = Path(args.out)
    out.mkdir(parents=True,exist_ok=True)
    if not torch.cuda.is_available():
        raise RuntimeError("Primary Qwen 7B 4-bit inference requires the authorized CUDA GPU")
    free,total = torch.cuda.mem_get_info()
    if free<8*1024**3:
        raise RuntimeError("GPU not free for Qwen; run after DTI benchmarks finish")
    torch.manual_seed(42)
    prompts = {document["pmid"]:messages_with_sentence_offsets(document) for document in documents}
    prompt_hash = hashlib.sha256(json.dumps(prompts,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    config = {"repo_id":MODEL,"commit":lock["commit"],"model_lock_sha256":digest(args.model_lock),
              "abstracts_sha256":digest(args.abstracts),"entities_sha256":digest(args.entities),
              "gold_sha256":digest(args.gold) if args.gold else None,"prompt_sha256":prompt_hash,
              "prompt_policy":"unchanged existing schema prompt plus exact sentence candidates/offsets",
              "script_sha256":digest(__file__),"batch_size":args.batch_size,"max_new_tokens":args.max_new_tokens,
              "max_input_tokens":args.max_input_tokens,"do_sample":False,"seed":42,
              "quantization":"bitsandbytes NF4 4bit double quantization, BF16 computation","no_finetuning":True,
              "selection":"all 750 dev documents; errors remain abstentions; prompts never include gold relations"}
    frozen = out/"inference_lock.json"
    if frozen.exists():
        if json.loads(frozen.read_text())!=config:
            raise ValueError("Resume config changed; use a new output directory")
    else:
        save(frozen,config)
    responses = {}
    response_path = out/"responses.jsonl"
    if response_path.exists():
        for line in response_path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row["pmid"] in responses or row["pmid"] not in prompts:
                raise ValueError("Duplicate or unexpected saved response PMID")
            responses[row["pmid"]] = row
    tokenizer = AutoTokenizer.from_pretrained(args.model_dir,local_files_only=True,trust_remote_code=False,padding_side="left")
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    quantization = BitsAndBytesConfig(load_in_4bit=True,bnb_4bit_compute_dtype=torch.bfloat16,
                                     bnb_4bit_quant_type="nf4",bnb_4bit_use_double_quant=True)
    model = AutoModelForCausalLM.from_pretrained(args.model_dir,local_files_only=True,trust_remote_code=False,
                                               quantization_config=quantization,device_map={"":0},torch_dtype=torch.bfloat16,
                                               attn_implementation="sdpa")
    model.eval()
    todo = [document for document in documents if document["pmid"] not in responses]
    started = time.monotonic()
    with open(response_path,"a",encoding="utf-8") as stream:
        for position in range(0,len(todo),args.batch_size):
            batch = todo[position:position+args.batch_size]
            texts = [tokenizer.apply_chat_template(prompts[document["pmid"]],tokenize=False,add_generation_prompt=True) for document in batch]
            lengths = [len(tokenizer.encode(text,add_special_tokens=False)) for text in texts]
            valid = [(document,text,length) for document,text,length in zip(batch,texts,lengths) if length<=args.max_input_tokens]
            records = [{"pmid":document["pmid"],"status":"context_overflow","response":"","prompt_tokens":length}
                       for document,length in zip(batch,lengths) if length>args.max_input_tokens]
            if valid:
                encoded = tokenizer([text for _,text,_ in valid],padding=True,return_tensors="pt",add_special_tokens=False).to("cuda")
                try:
                    with torch.inference_mode():
                        output = model.generate(**encoded,max_new_tokens=args.max_new_tokens,do_sample=False,
                                                pad_token_id=tokenizer.pad_token_id,eos_token_id=tokenizer.eos_token_id)
                    generated = output[:,encoded.input_ids.shape[1]:]
                    for (document,_,length),tokens in zip(valid,generated):
                        count = int(tokens.ne(tokenizer.pad_token_id).sum())
                        text = tokenizer.decode(tokens,skip_special_tokens=True)
                        records.append({"pmid":document["pmid"],"status":"generated","response":text,"prompt_tokens":length,
                                        "generated_tokens":count,"hit_output_limit":count>=args.max_new_tokens})
                except (RuntimeError,ValueError) as error:
                    if isinstance(error,torch.OutOfMemoryError):
                        torch.cuda.empty_cache()
                    records.extend({"pmid":document["pmid"],"status":"generation_error","response":"","error":str(error),"prompt_tokens":length}
                                   for document,_,length in valid)
            for record in records:
                responses[record["pmid"]] = record
                stream.write(json.dumps(record,ensure_ascii=False)+"\n")
            stream.flush()
            print(f"documents {len(responses)}/750 elapsed {time.monotonic()-started:.1f}s",flush=True)
    result = analyze_responses(documents,responses,out,args.gold,args.abstracts,args.entities)
    result.update({"completed_utc":now(),"elapsed_this_invocation_seconds":time.monotonic()-started,
                   "generated_output_limit_documents":sum(bool(row.get("hit_output_limit")) for row in responses.values()),
                   "inference_lock_sha256":digest(frozen),"responses_sha256":digest(response_path),
                   "runtime":{"python":platform.python_version(),"torch":torch.__version__,"cuda":torch.version.cuda,
                              "gpu":torch.cuda.get_device_name(0),"transformers":transformers.__version__,"bitsandbytes":bitsandbytes.__version__},
                   "contamination_note":"Public DrugProt/PubMed may occur in pretraining; no guarantee of unseen pretraining documents"})
    save(out/"inference_summary.json",result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode",choices=["download","infer"])
    parser.add_argument("--model-dir",type=Path,required=True)
    parser.add_argument("--model-lock",type=Path,required=True)
    parser.add_argument("--revision",default="main")
    parser.add_argument("--abstracts",type=Path)
    parser.add_argument("--entities",type=Path)
    parser.add_argument("--gold",type=Path)
    parser.add_argument("--out",type=Path)
    parser.add_argument("--batch-size",type=int,default=4)
    parser.add_argument("--max-new-tokens",type=int,default=1024)
    parser.add_argument("--max-input-tokens",type=int,default=8192)
    args = parser.parse_args()
    if args.mode=="infer" and not all((args.abstracts,args.entities,args.out)):
        parser.error("Inference needs abstracts, entities and output directory")
    result = download_model(args.model_dir,args.model_lock,args.revision) if args.mode=="download" else infer(args)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
