"""Textual quotation grounding of frozen1198 PubMed candidate responses.

This separate post-hoc operation reads no relation gold, invokes no model and
does not modify the original strict0 results, dictionaries, source text or
responses. Source quotes remain in ignored local data, not in the Git summary.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re

from nutriomics_evidence.extraction import parse_qwen, write_relations
from nutriomics_evidence.literature import annotate_relations
from nutriomics_evidence.quote_grounding import parse_quote_grounded, POLICY_VERSION

ACTUAL_RESPONSES_SHA256 = '1f77473db47265de9dcd170bd8d66bc2050867e29d83dd32e2263a136459230c'
EMPTY_RESPONSE = '{"relations": []}'


def digest_bytes(value):
    return hashlib.sha256(value).hexdigest()


def digest(path):
    return digest_bytes(Path(path).read_bytes())


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def read_verified(path, expected=None):
    raw = Path(path).read_bytes()
    if expected is not None and digest_bytes(raw) != expected:
        raise ValueError('Frozen artifact hash mismatch: ' + str(path))
    return raw


def jsonl_bytes(raw):
    # U+2028/U+2029 in source strings must not split physical JSONL records.
    with io.StringIO(raw.decode('utf-8')) as stream:
        return [json.loads(line) for line in stream if line.strip()]


def validate_cohort(documents, records, lock, *, expected_documents=1198, expected_eligible=202):
    if (lock.get('documents') != expected_documents or lock.get('eligible_documents') != expected_eligible
            or lock.get('gold_available') is not False or len(documents) != expected_documents
            or sum(document.get('qwen_eligible') is True for document in documents) != expected_eligible):
        raise ValueError('Frozen cohort/inference-lock count or no-gold contract mismatch')
    pmids = [document['pmid'] for document in documents]
    ids = [record.get('pmid') for record in records]
    if (any(not isinstance(pmid, str) or not pmid.isdigit() for pmid in pmids + ids)
            or len(set(pmids)) != len(pmids) or len(set(ids)) != len(ids)):
        raise ValueError('Malformed or duplicate cohort/response PMID')
    if set(ids) - set(pmids):
        raise ValueError('Response from a different cohort')
    if set(pmids) - set(ids):
        raise ValueError('Missing frozen response; do not convert it into a model error or a scoped abstention')
    responses = {record['pmid']: record for record in records}
    for document in documents:
        row = responses[document['pmid']]
        if not isinstance(document.get('qwen_eligible'), bool):
            raise ValueError('Prepared eligibility must be an explicit boolean')
        if not document['qwen_eligible']:
            if (row.get('status') != 'no_comention_abstention' or row.get('response') != EMPTY_RESPONSE
                    or row.get('model_invoked') is not False
                    or row.get('reason') != document.get('abstention_reason')):
                raise ValueError('Noneligible record must remain its original explicit uninvoked empty abstention')
        elif row.get('status') == 'generation_error':
            if row.get('response') != '' or not isinstance(row.get('error'), str) or not row['error']:
                raise ValueError('Generation error must retain empty output and its actual error receipt')
        elif row.get('status') != 'generated' or not isinstance(row.get('response'), str):
            raise ValueError('Eligible record requires generated output or an explicit generation-error receipt')
    return responses


def validate_inference_sources(lock, preparation_raw, preparation, *, code_files=None):
    if lock.get('preparation_lock_sha256') != digest_bytes(preparation_raw):
        raise ValueError('Inference lock references different preparation')
    if lock.get('documents_sha256') != preparation['files']['documents.jsonl']:
        raise ValueError('Inference lock references different source documents')
    if lock.get('literature_module_sha256') != preparation.get('module_sha256'):
        raise ValueError('Preparation/inference literature-module version mismatch')
    for key, path in (code_files or {}).items():
        if lock.get(key) != digest(path):
            raise ValueError('Frozen inference source code mismatch: ' + key)


def grounding_candidates(documents, responses):
    accepted, reports = [], []
    statuses, errors, reasons = Counter(), Counter(), Counter()
    strict_reasons, strict_rejected = Counter(), 0
    strict_accepted = 0
    for document in documents:
        row = responses[document['pmid']]
        statuses[row['status']] += 1
        if row['status'] == 'no_comention_abstention':
            reports.append({'pmid': document['pmid'], 'status': row['status'], 'accepted': [], 'rejected': [],
                'reason': row['reason'], 'model_invoked': False})
            continue
        # Recompute the existing frozen parser's counters without writing its
        # outputs. Empty generation errors also counted as its JSON errors.
        try:
            original = parse_qwen(row['response'], document)
            strict_accepted += len(original['accepted'])
            strict_rejected += len(original['rejected'])
            for rejection in original['rejected']:
                strict_reasons.update(rejection['reasons'])
        except (ValueError, TypeError, KeyError):
            strict_reasons['invalid_json_or_schema'] += 1
        if row['status'] == 'generation_error':
            errors['generation_error_abstention'] += 1
            reports.append({'pmid': document['pmid'], 'status': 'generation_error', 'accepted': [], 'rejected': [],
                'error_kind': 'CUDA_out_of_memory' if 'CUDA out of memory' in row['error'] else 'other_generation_error',
                'error_receipt_sha256': digest_bytes(row['error'].encode()), 'not_missing_response': True})
            continue
        try:
            parsed = parse_quote_grounded(row['response'], document)
            parsed['accepted'] = annotate_relations(parsed['accepted'], document)
            for candidate in parsed['accepted']:
                candidate.update({'corpus': 'literature_ctd_v2_frozen1198',
                    'source_doi': document['source'].get('doi'), 'source_pmcid': document['source'].get('pmcid'),
                    'source_topics': document['source'].get('topics'),
                    'normalized_ids_status': 'CTD dictionary candidates; exact lexical match is not independent identity verification',
                    'dictionary_NER_validated': False, 'human_semantic_review_completed': False,
                    'clinical_efficacy': None, 'binding_affinity': None, 'species': None,
                    'expert_review_status': 'pending', 'semantic_entailment_validated': False,
                    'evaluation_status': 'Post-hoc textual grounding; gold-free corpus; not an accuracy evaluation'})
            accepted.extend(parsed['accepted'])
            for rejection in parsed['rejected']:
                reasons.update(rejection['reasons'])
            parsed['status'] = 'generated'
            reports.append(parsed)
        except (ValueError, TypeError, KeyError) as error:
            errors['generated_invalid_JSON_or_schema_abstention'] += 1
            reports.append({'pmid': document['pmid'], 'status': 'generated', 'accepted': [], 'rejected': [], 'error': str(error)})
    return accepted, reports, {'response_status_counts': dict(statuses), 'document_error_counts': dict(errors),
        'rejection_reason_counts': dict(reasons), 'rejected_relation_rows': sum(len(report['rejected']) for report in reports),
        'original_strict_accepted_rows': strict_accepted, 'original_strict_rejected_rows': strict_rejected,
        'original_strict_rejection_reason_counts': dict(strict_reasons)}


def run(args):
    root = args.root.resolve()
    prepared, inference = root/'data/literature_ctd_v2', root/'data/literature_qwen_v1'
    original_articles = root/'data/pubmed_approved6/articles.jsonl'
    original_manifest = root/'data/pubmed_approved6/source_manifest.json'
    protected_code = {
        'script_sha256': root/'scripts/run_literature_qwen.py',
        'helper_script_sha256': root/'scripts/run_qwen.py',
        'literature_module_sha256': root/'src/nutriomics_evidence/literature.py',
        'extraction_module_sha256': root/'src/nutriomics_evidence/extraction.py'}
    protected = [path for path in prepared.iterdir() if path.is_file()]
    protected += [path for path in inference.iterdir() if path.is_file()]
    protected += [original_articles, original_manifest, *protected_code.values(),
        root/'src/nutriomics_evidence/quote_grounding.py']
    before = {path.relative_to(root).as_posix(): digest(path) for path in protected}
    summary = json.loads(read_verified(inference/'inference_summary.json'))
    response_raw = read_verified(inference/'responses.jsonl', ACTUAL_RESPONSES_SHA256)
    if summary['responses_sha256'] != ACTUAL_RESPONSES_SHA256:
        raise ValueError('Original response receipt mismatch')
    lock_raw = read_verified(inference/'inference_lock.json', summary['inference_lock_sha256'])
    lock = json.loads(lock_raw)
    preparation_raw = read_verified(prepared/'preparation_lock.json', lock['preparation_lock_sha256'])
    preparation = json.loads(preparation_raw)
    validate_inference_sources(lock, preparation_raw, preparation, code_files=protected_code)
    if (lock.get('model') != 'Qwen/Qwen2.5-7B-Instruct'
            or lock.get('commit') != 'a09a35458c702b33eeacc393d103063234e8bc28'
            or lock.get('model_lock_sha256') != '97cc2ea88e75a551d2d15cbb74257981e499c2e6094805bb5a02940f3d89a361'):
        raise ValueError('Different frozen model provenance')
    cached = {}
    for name, expected in preparation['files'].items():
        if Path(name).name != name:
            raise ValueError('Prepared file name escapes its source directory')
        cached[name] = read_verified(prepared/name, expected)
    read_verified(original_articles, preparation['articles_sha256'])
    read_verified(original_manifest, preparation['pubmed_source_manifest_sha256'])
    documents = jsonl_bytes(cached['documents.jsonl'])
    for document in documents:
        if digest_bytes(document['text'].encode()) != document['text_sha256']:
            raise ValueError('Prepared original text hash mismatch')
    responses = validate_cohort(documents, jsonl_bytes(response_raw), lock)
    # Recreate the original prompt hash without a tokenizer/model or gold.
    from run_qwen import messages_with_sentence_offsets
    prompts = {document['pmid']: messages_with_sentence_offsets({key: document[key] for key in ('pmid', 'text', 'entities')})
               for document in documents if document['qwen_eligible']}
    prompt_sha = digest_bytes(json.dumps(prompts, sort_keys=True, ensure_ascii=False).encode())
    if prompt_sha != lock['prompt_sha256']:
        raise ValueError('Frozen source prompt differs from the original inference lock')
    out = args.out.resolve()
    if (out.exists() or any(out == path or out in path.parents for path in protected)
            or any(out.is_relative_to(directory.resolve()) for directory in (prepared, inference, original_articles.parent))):
        raise ValueError('Use a new output directory outside immutable source artifacts')
    candidates, reports, counters = grounding_candidates(documents, responses)
    if (counters['original_strict_accepted_rows'] != summary['accepted_relation_rows']
            or counters['original_strict_rejected_rows'] != summary['rejected_relation_rows']
            or counters['original_strict_rejection_reason_counts'] != summary['rejection_reason_counts']
            or counters['response_status_counts'] != summary['response_status_counts']):
        raise ValueError('Frozen original strict result/counters do not reproduce')
    out.mkdir(parents=True)
    save(out/'candidate_relations.json', candidates)
    write_relations(out/'candidate_relations.tsv', candidates)
    save(out/'validation_reports.json', reports)
    error_groups = []
    for message, count in Counter(row['error'] for row in responses.values() if row['status'] == 'generation_error').items():
        def detail(pattern):
            match = re.search(pattern, message)
            return match[1] if match else None
        error_groups.append({'error_kind': 'CUDA_out_of_memory' if 'CUDA out of memory' in message else 'other_generation_error',
            'documents': count, 'message_sha256': digest_bytes(message.encode()),
            'requested_allocation': detail(r'Tried to allocate ([0-9.]+ [GM]iB)'),
            'GPU_free_memory': detail(r'of which ([0-9.]+ [GM]iB) is free'),
            'pmids': [row['pmid'] for row in responses.values() if row.get('error') == message]})
    result = {'created_utc': datetime.now(timezone.utc).isoformat(), 'policy_version': POLICY_VERSION,
        'operation': 'Separate post-hoc exact-quotation textual grounding of already generated literature responses',
        'corpus': 'literature_ctd_v2_frozen1198', 'documents': 1198, 'eligible_documents': 202,
        **counters, 'accepted_relation_rows': len(candidates),
        'accepted_rows_with_reconstructed_offsets': sum(row['grounding_receipt']['offsets_changed'] for row in candidates),
        'candidate_papers': len({row['pmid'] for row in candidates}),
        'report_coverage': {'documents': len(reports), 'missing': 0, 'duplicate': 0, 'unexpected': 0},
        'source_artifact_sha256': before, 'articles_sha256': preparation['articles_sha256'],
        'original_pubmed_source_manifest_sha256': preparation['pubmed_source_manifest_sha256'],
        'preparation_lock_sha256': digest_bytes(preparation_raw), 'inference_lock_sha256': digest_bytes(lock_raw),
        'original_responses_sha256': digest_bytes(response_raw), 'source_prompt_sha256_verified': prompt_sha,
        'dictionary_sha256': preparation['files']['dictionary.json'],
        'script_sha256': digest(Path(__file__)), 'parser_sha256': digest(root/'src/nutriomics_evidence/quote_grounding.py'),
        'candidate_JSON_sha256': digest(out/'candidate_relations.json'),
        'candidate_TSV_sha256': digest(out/'candidate_relations.tsv'),
        'generation_error_groups': error_groups, 'original_strict_result_modified': False,
        'gold_available': False, 'gold_used_for_grounding': False, 'precision': None, 'recall': None, 'f1': None,
        'food_domain_accuracy': None, 'dictionary_NER_accuracy': None,
        'semantic_entailment_validated': False, 'expert_approved_relations': None,
        'generation_schema_evaluated': False, 'API_grounding_evaluated': False,
        'model_invoked_in_this_operation': False, 'model_files_opened_or_modified': False,
        'model_provenance_from_frozen_inference': {key: lock[key] for key in ('model', 'commit', 'model_lock_sha256')},
        'model_weight_hashes_reverified_in_this_operation': False,
        'raw_source_and_quote_redistribution': 'Ignored local data only; this summary contains no source quotations',
        'binding_affinity': None, 'clinical_efficacy': None, 'species_inferred': False,
        'interpretation': 'Candidates have exact source quotation and both dictionary mention spans. This does not validate NER, normalized molecular identity, relation entailment, binding, causality or clinical benefit. All candidates require expert review; original strict0 remains separately reported.'}
    result['source_files_and_original_strict_outputs_unchanged'] = all(digest(root/path) == expected for path, expected in before.items())
    if not result['source_files_and_original_strict_outputs_unchanged'] or len(reports) != 1198:
        raise ValueError('Frozen source changed or full cohort report incomplete')
    save(out/'diagnostic_summary.json', result)
    save(root/'docs/literature/quote_grounding_diagnostic_summary.json', result)
    print(json.dumps({'documents': 1198, 'statuses': counters['response_status_counts'],
        'accepted_candidates': len(candidates), 'candidate_papers': result['candidate_papers'],
        'original_strict_accepted': counters['original_strict_accepted_rows'], 'source_unchanged': True}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--out', type=Path, default=Path('data/literature_quote_grounding_v1'))
    run(parser.parse_args())
