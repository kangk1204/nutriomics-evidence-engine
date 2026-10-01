"""One separate fixed-batch1 operational retry of the eight frozen OOM records.

Original primary results remain unchanged. This script does not score relations,
read gold, repair responses, replace full-cohort outputs or claim output parity.
It refuses CPU/H200 fallback and never downloads model code or weights.
"""
from __future__ import annotations

import argparse
from collections import Counter
import gc
import hashlib
import io
import json
from pathlib import Path
import platform
import time

from run_qwen import verify_model, messages_with_sentence_offsets, digest, save, now, MODEL
from nutriomics_evidence.literature import load_prepared

SOURCE_RESPONSE_SHA = '1f77473db47265de9dcd170bd8d66bc2050867e29d83dd32e2263a136459230c'
MODEL_COMMIT = 'a09a35458c702b33eeacc393d103063234e8bc28'
MODEL_LOCK_SHA = '97cc2ea88e75a551d2d15cbb74257981e499c2e6094805bb5a02940f3d89a361'
OOM_PMIDS = ['10835904', '11097107', '11677359', '11815511', '12037693', '12122105', '12579406', '12661920']
GPU_NAME = 'NVIDIA GeForce RTX 5060 Ti'
SETTINGS = {'batch_size': 1, 'max_input_tokens': 8192, 'max_new_tokens': 1024,
            'seed': 42, 'do_sample': False, 'quantization': 'bitsandbytes NF4 4bit double quantization, BF16 computation',
            'local_files_only': True, 'trust_remote_code': False, 'device': 'cuda:0'}


def read_jsonl_bytes(raw):
    with io.StringIO(raw.decode('utf-8')) as stream:
        return [json.loads(line) for line in stream if line.strip()]


def select_oom_documents(documents, records, *, expected_pmids=OOM_PMIDS):
    if len(documents) != 1198 or len({d['pmid'] for d in documents}) != 1198:
        raise ValueError('Require the frozen1198 source cohort')
    lookup = {d['pmid']: d for d in documents}
    pmids = [row.get('pmid') for row in records]
    if len(pmids) != 1198 or len(set(pmids)) != len(pmids) or set(pmids) != set(lookup):
        raise ValueError('Original response coverage/cohort changed')
    eligible = sum(d['qwen_eligible'] is True for d in documents)
    if eligible != 202:
        raise ValueError('Frozen eligible cohort changed')
    selected = set()
    statuses = Counter()
    for row in records:
        document = lookup[row['pmid']]
        status = row.get('status')
        statuses[status] += 1
        if not document['qwen_eligible']:
            if (status != 'no_comention_abstention' or row.get('response') != '{"relations": []}'
                    or row.get('model_invoked') is not False or row.get('reason') != document['abstention_reason']):
                raise ValueError('Original explicit uninvoked abstention changed')
        elif status == 'generation_error':
            if row.get('response') != '' or not isinstance(row.get('error'), str) or 'CUDA out of memory' not in row['error']:
                raise ValueError('Only original explicit CUDA OOM errors may be retried')
            selected.add(row['pmid'])
        elif status != 'generated' or not isinstance(row.get('response'), str):
            raise ValueError('Missing/unsupported status cannot be relabelled as OOM')
    if statuses != {'generated': 194, 'generation_error': 8, 'no_comention_abstention': 996}:
        raise ValueError('Original full-cohort operational status counts changed')
    if selected != set(expected_pmids) or len(expected_pmids) != 8:
        raise ValueError('Exactly the originally frozen eight OOM PMIDs are required')
    # Preserve native prepared order, independently of response-file grouping.
    return [d for d in documents if d['pmid'] in selected]


def check_cuda(torch):
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA unavailable; CPU fallback is prohibited for this retry')
    if torch.cuda.device_count() != 1 or torch.cuda.get_device_name(0) != GPU_NAME:
        raise RuntimeError('Only the authorized single RTX5060Ti GPU is permitted; no H200/other device fallback')
    free, total = torch.cuda.mem_get_info(0)
    if free < 8 * 1024**3:
        raise RuntimeError('Insufficient free GPU memory before model load; wait for the authorized GPU')
    return {'device_count': 1, 'GPU': GPU_NAME, 'free_bytes_before_model': free, 'total_bytes': total,
            'routing_authorized_endpoint': '100.84.183.6', 'CPU_fallback': False, 'H200_allowed': False}


def preserve_new_run(out, config):
    if out.exists():
        frozen = out/'retry_lock.json'
        if frozen.exists() and json.loads(frozen.read_text(encoding='utf-8')) != config:
            raise ValueError('Frozen retry parameters/source/cohort changed')
        raise FileExistsError('Retry output already exists; never re-execute or overwrite its locked run')
    out.mkdir(parents=True)
    save(out/'retry_lock.json', config)


def source_configuration(root, prepared, inference, model_dir, model_lock, out):
    root = Path(root).resolve()
    for path in (prepared, inference, model_dir, model_lock, out):
        if not Path(path).resolve().is_relative_to(root):
            raise ValueError('All inputs/outputs must stay inside the isolated evidence checkout')
    if any(out.resolve().is_relative_to(path.resolve()) for path in (prepared, inference, model_dir)):
        raise ValueError('Retry output must stay outside frozen preparation/inference/model directories')
    raw = (inference/'responses.jsonl').read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_RESPONSE_SHA:
        raise ValueError('Original frozen response SHA mismatch')
    summary = json.loads((inference/'inference_summary.json').read_text(encoding='utf-8'))
    if (summary['responses_sha256'] != SOURCE_RESPONSE_SHA
            or digest(inference/'inference_lock.json') != summary['inference_lock_sha256']):
        raise ValueError('Original inference receipt/lock changed')
    original = json.loads((inference/'inference_lock.json').read_text(encoding='utf-8'))
    documents, preparation = load_prepared(prepared)
    if (digest(prepared/'preparation_lock.json') != original['preparation_lock_sha256']
            or preparation['files']['documents.jsonl'] != original['documents_sha256']
            or original['model'] != MODEL or original['commit'] != MODEL_COMMIT
            or original['model_lock_sha256'] != MODEL_LOCK_SHA or digest(model_lock) != MODEL_LOCK_SHA
            or original.get('documents') != 1198 or original.get('eligible_documents') != 202
            or original.get('gold_available') is not False):
        raise ValueError('Original source/model/cohort inference lock mismatch')
    protected_code = {'script_sha256': root/'scripts/run_literature_qwen.py',
        'helper_script_sha256': root/'scripts/run_qwen.py',
        'literature_module_sha256': root/'src/nutriomics_evidence/literature.py',
        'extraction_module_sha256': root/'src/nutriomics_evidence/extraction.py'}
    for key, path in protected_code.items():
        if original[key] != digest(path):
            raise ValueError('Original frozen inference code bytes changed: ' + key)
    selected = select_oom_documents(documents, read_jsonl_bytes(raw))
    all_prompts = {d['pmid']: messages_with_sentence_offsets({key: d[key] for key in ('pmid', 'text', 'entities')})
                   for d in documents if d['qwen_eligible']}
    source_prompt_sha = hashlib.sha256(json.dumps(all_prompts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if source_prompt_sha != original['prompt_sha256']:
        raise ValueError('Original full eligible prompt identity changed')
    prompts = {d['pmid']: all_prompts[d['pmid']] for d in selected}
    selected_prompt_sha = hashlib.sha256(json.dumps(prompts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    protected = [path for path in prepared.iterdir() if path.is_file()]
    protected += [path for path in inference.iterdir() if path.is_file()]
    protected += [*protected_code.values(), model_lock]
    source_hashes = {path.relative_to(root).as_posix(): digest(path) for path in protected}
    config = {'protocol': 'literature-eight-OOM-fixed-batch1-operational-retry-v1',
        'retry_pmids': [d['pmid'] for d in selected], 'expected_retry_documents': 8,
        'full_source_documents': 1198, 'original_source_response_sha256': SOURCE_RESPONSE_SHA,
        'original_inference_lock_sha256': digest(inference/'inference_lock.json'),
        'preparation_lock_sha256': digest(prepared/'preparation_lock.json'),
        'documents_sha256': preparation['files']['documents.jsonl'],
        'original_full_eligible_prompt_sha256': source_prompt_sha,
        'selected_exact_original_prompts_sha256': selected_prompt_sha,
        'model': MODEL, 'model_commit': MODEL_COMMIT, 'model_lock_sha256': MODEL_LOCK_SHA,
        'retry_script_sha256': digest(Path(__file__)), 'original_source_artifact_sha256': source_hashes,
        **SETTINGS, 'original_primary_results_modified': False, 'gold_available': False,
        'gold_used': False, 'full_corpus_rescoring': False, 'output_parity_claim': False,
        'purpose': 'Operational generation-success check only; no extraction accuracy, binding, causal or clinical claim',
        'authorized_GPU_endpoint': '100.84.183.6', 'CPU_server_used': False, 'H200_used': False}
    return selected, prompts, config, source_hashes


def infer(args):
    root = args.root.resolve()
    prepared, inference = root/'data/literature_ctd_v2', root/'data/literature_qwen_v1'
    model_dir = args.model_dir.resolve() if args.model_dir else root/'data/models/qwen2.5-7b'
    model_lock = args.model_lock.resolve() if args.model_lock else root/'data/qwen_model_lock.json'
    out = args.out.resolve() if args.out.is_absolute() else root/args.out
    selected, prompts, config, source_hashes = source_configuration(root, prepared, inference, model_dir, model_lock, out)
    # Refuse any existing output before doing expensive model verification.
    if out.exists():
        preserve_new_run(out, config)
    import torch
    import transformers
    import bitsandbytes
    from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
    preflight = check_cuda(torch)
    verified_weights = verify_model(model_dir, model_lock)
    if verified_weights['commit'] != MODEL_COMMIT or verified_weights.get('trust_remote_code') is not False:
        raise ValueError('Pinned model/remote-code metadata mismatch')
    # The lock is created before any model generation and contains no timestamps
    # that could disguise changed source/config as an identical rerun.
    preserve_new_run(out, config)
    save(out/'GPU_preflight.json', {**preflight, 'checked_utc': now(), 'all_model_files_sha256_verified': True,
        'model_total_bytes': verified_weights['total_bytes']})
    runtime = {'python': platform.python_version(), 'torch': torch.__version__, 'transformers': transformers.__version__,
        'bitsandbytes': bitsandbytes.__version__, 'cuda_build': torch.version.cuda, 'GPU': GPU_NAME}
    torch.manual_seed(42)
    started = time.monotonic()
    responses, model, tokenizer = [], None, None
    try:
        tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True, trust_remote_code=False, padding_side='left')
        if tokenizer.pad_token_id is None:
            tokenizer.pad_token = tokenizer.eos_token
        quantization = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_quant_type='nf4', bnb_4bit_use_double_quant=True)
        model = AutoModelForCausalLM.from_pretrained(model_dir, local_files_only=True, trust_remote_code=False,
            quantization_config=quantization, device_map={'': 0}, torch_dtype=torch.bfloat16, attn_implementation='sdpa')
        model.eval()
    except (RuntimeError, ValueError, TypeError) as error:
        responses = [{'pmid': d['pmid'], 'status': 'generation_error', 'response': '', 'error': str(error),
            'error_stage': 'model_load', 'error_kind': 'CUDA_out_of_memory' if 'out of memory' in str(error).lower() else 'other_runtime_error'}
            for d in selected]
    with (out/'responses.jsonl').open('w', encoding='utf-8', newline='\n') as stream:
        if responses:
            for row in responses:
                stream.write(json.dumps(row, ensure_ascii=False)+'\n')
        else:
            for number, document in enumerate(selected, 1):
                encoded, output = None, None
                begin = time.monotonic()
                try:
                    text = tokenizer.apply_chat_template(prompts[document['pmid']], tokenize=False, add_generation_prompt=True)
                    length = len(tokenizer.encode(text, add_special_tokens=False))
                    if length > 8192:
                        row = {'pmid': document['pmid'], 'status': 'context_overflow_abstention', 'response': '', 'prompt_tokens': length}
                    else:
                        encoded = tokenizer([text], padding=True, return_tensors='pt', add_special_tokens=False).to('cuda')
                        with torch.inference_mode():
                            output = model.generate(**encoded, max_new_tokens=1024, do_sample=False,
                                pad_token_id=tokenizer.pad_token_id, eos_token_id=tokenizer.eos_token_id)
                        tokens = output[0, encoded.input_ids.shape[1]:]
                        count = int(tokens.ne(tokenizer.pad_token_id).sum())
                        row = {'pmid': document['pmid'], 'status': 'generated',
                            'response': tokenizer.decode(tokens, skip_special_tokens=True),
                            'prompt_tokens': length, 'generated_tokens': count, 'hit_output_limit': count >= 1024}
                except (RuntimeError, ValueError, TypeError) as error:
                    row = {'pmid': document['pmid'], 'status': 'generation_error', 'response': '', 'error': str(error),
                        'error_stage': 'single_document_generation',
                        'error_kind': 'CUDA_out_of_memory' if 'out of memory' in str(error).lower() else 'other_runtime_error'}
                row.update(elapsed_seconds=time.monotonic()-begin, batch_size=1,
                    original_primary_status='generation_error', original_primary_error_kind='CUDA_out_of_memory',
                    operational_retry_only=True, semantic_entailment_validated=False)
                responses.append(row)
                stream.write(json.dumps(row, ensure_ascii=False)+'\n');stream.flush()
                del encoded, output
                gc.collect();torch.cuda.empty_cache()
                print(f'retry {number}/8 {document["pmid"]} status={row["status"]}', flush=True)
    del model, tokenizer
    gc.collect();torch.cuda.empty_cache()
    # Re-read actual weight bytes and original sources after the operation.
    model_unchanged = verify_model(model_dir, model_lock) == verified_weights
    source_unchanged = all(digest(root/path) == expected for path, expected in source_hashes.items())
    if len(responses) != 8 or [row['pmid'] for row in responses] != config['retry_pmids']:
        raise ValueError('Supplemental retry coverage failure')
    receipt = {'completed_utc': now(), 'runtime': runtime, 'elapsed_seconds': time.monotonic()-started,
        'retry_lock_sha256': digest(out/'retry_lock.json'), 'responses_sha256': digest(out/'responses.jsonl'),
        'retry_documents': 8, 'response_status_counts': dict(Counter(row['status'] for row in responses)),
        'generation_error_kinds': dict(Counter(row['error_kind'] for row in responses if row['status']=='generation_error')),
        'generated_nonempty_responses': sum(row['status']=='generated' and bool(row['response']) for row in responses),
        'generated_output_limit_documents': sum(bool(row.get('hit_output_limit')) for row in responses),
        'retry_pmids': config['retry_pmids'], 'original_primary_OOM_documents_remain': 8,
        'original_primary_results_modified': False, 'original_source_and_code_bytes_unchanged': source_unchanged,
        'all_model_files_hashes_reverified_unchanged': model_unchanged,
        'full_corpus_rescoring': False, 'relation_gold_used': False, 'extraction_accuracy': None,
        'precision': None, 'recall': None, 'f1': None, 'semantic_entailment_validated': False,
        'clinical_efficacy': None, 'binding_affinity': None, 'output_parity_validated': False,
        'interpretation': 'Supplemental fixed-batch1 operational retry success/failure only. Original batch8 OOM and strict extraction results remain primary and unchanged.'}
    save(out/'operational_receipt.json', receipt)
    if not source_unchanged or not model_unchanged:
        raise RuntimeError('Original source/code/model bytes changed; supplemental operation is not valid')
    save(root/'docs/literature/oom_retry_protocol.json', {'protocol': config, 'GPU_preflight': preflight,
        'model_files_verified_before_and_after': True, 'actual_execution': receipt})
    print(json.dumps({'retry_documents': 8, 'statuses': receipt['response_status_counts'],
        'original_primary_unchanged': True, 'operational_only': True}))
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--out', type=Path, default=Path('data/literature_oom_retry_batch1_v1'))
    parser.add_argument('--model-dir', type=Path)
    parser.add_argument('--model-lock', type=Path)
    infer(parser.parse_args())
