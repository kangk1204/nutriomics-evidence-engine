"""Diagnose frozen Qwen failures and separately score exact-quote postprocessing.

Reference relations are opened only after all grounding outputs and their lock
have been written. Original inference artifacts and strict results are immutable.
No generation, retraining, schema repair, parameter search or API call occurs.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from nutriomics_evidence.extraction import load_drugprot, parse_qwen, write_relations, evaluate
from nutriomics_evidence.quote_grounding import exact_occurrences, parse_quote_grounded, POLICY_VERSION

NATIVE_SHA = {
    'abstracts': 'dc9a9deb6c4e37bc67380b888718689f3f11edc4e09de838891674d6565d89b8',
    'entities': '212c88668c611edf067ae39f052494febbb8dcb2fc81af8160507a4a176c667e',
    'gold': '6df63c08a7e1ae50d9bf32a2c91eeec641e9b879cfd3b1a4cec15b0b2781403d',
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def load_jsonl(path):
    # Physical JSONL newlines; do not split on source U+2028/U+2029 characters.
    with Path(path).open(encoding='utf-8') as handle:
        return [json.loads(line) for line in handle if line.strip()]


def failure_analysis(documents, responses, frozen_reports):
    raw_json, tails, top_schema = Counter(), Counter(), Counter()
    offsets, quotes, boundaries, entity_errors = Counter(), Counter(), Counter(), Counter()
    generated_limits, error_rows = [], []
    total_rows = bad_span_rows = exact_quote_both = 0
    strict_reason_counts = Counter()
    for report in frozen_reports:
        for row in report['rejected']:
            strict_reason_counts.update(row['reasons'])
    for document in documents:
        response = responses[document['pmid']]
        text = response['response']
        if response['status'] == 'generation_error':
            error_rows.append(response)
        if response.get('hit_output_limit'):
            generated_limits.append(document['pmid'])
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as error:
            raw_json[(response['status'], error.msg)] += 1
            if error.msg == 'Extra data':
                remainder = text[error.pos:].strip()
                if remainder == '```':
                    label = 'trailing_markdown_closing_fence'
                elif remainder in ('\\n', '\\\\n'):
                    label = 'trailing_literal_backslash_n'
                else:
                    label = 'other_extra_data'
                tails[label] += 1
            continue
        if not isinstance(payload, dict) or set(payload) != {'relations'} or not isinstance(payload.get('relations'), list):
            label = 'wrong_top_level_type' if not isinstance(payload, dict) else 'wrong_top_level_keys' if set(payload) != {'relations'} else 'relations_not_list'
            top_schema[label] += 1
            continue
        report = parse_qwen(payload, document)
        bad_indices = {row['index'] for row in report['rejected'] if 'invalid_evidence_span' in row['reasons']}
        lookup = {entity['id']: entity for entity in document['entities']}
        for index, row in enumerate(payload['relations']):
            total_rows += 1
            if index not in bad_indices:
                continue
            bad_span_rows += 1
            start, end = row.get('evidence_start'), row.get('evidence_end')
            valid_type = all(isinstance(v, int) and not isinstance(v, bool) for v in (start, end))
            if not valid_type:
                offsets['non_integer_or_boolean_offsets'] += 1
            elif not 0 <= start < end <= len(document['text']):
                offsets['out_of_bounds_or_nonpositive_span'] += 1
            else:
                offsets['in_bounds_but_source_slice_differs_from_quote'] += 1
                if isinstance(row.get('evidence_text'), str) and end-start != len(row['evidence_text']):
                    offsets['supplied_span_length_differs_from_quote_length'] += 1
            quote = row.get('evidence_text')
            occurrences = exact_occurrences(document['text'], quote)
            label = 'missing_or_nonstring_quote' if not isinstance(quote, str) or not quote else 'no_exact_occurrence' if not occurrences else 'unique_exact_occurrence' if len(occurrences) == 1 else 'multiple_exact_occurrences'
            quotes[label] += 1
            a, b = lookup.get(row.get('arg1')), lookup.get(row.get('arg2'))
            if a is None or b is None:
                entity_errors['unknown_entity_id'] += 1
            elif a['type'] != 'CHEMICAL' or not b['type'].startswith('GENE'):
                entity_errors['native_argument_type_or_direction_wrong'] += 1
            else:
                if len(occurrences) == 1 and all(occurrences[0][0] <= entity['start'] and entity['end'] <= occurrences[0][1] for entity in (a, b)):
                    exact_quote_both += 1
                if valid_type:
                    for label, match in [('start_equals_native_arg1_start', start == a['start']),
                                         ('start_equals_native_arg2_start', start == b['start']),
                                         ('end_equals_native_arg1_end', end == a['end']),
                                         ('end_equals_native_arg2_end', end == b['end'])]:
                        if match:
                            boundaries[label] += 1
    groups = []
    for message, count in Counter(row['error'] for row in error_rows).items():
        def value(pattern):
            match = re.search(pattern, message)
            return match[1] if match else None
        matching = [row for row in error_rows if row['error'] == message]
        groups.append({'kind': 'CUDA_out_of_memory' if 'CUDA out of memory' in message else 'other_generation_error',
            'documents': count, 'error_message_sha256': hashlib.sha256(message.encode()).hexdigest(),
            'pmids': [row['pmid'] for row in matching],
            'requested_allocation': value(r'Tried to allocate ([0-9.]+ [GM]iB)'),
            'GPU_total_capacity': value(r'total capacity of ([0-9.]+ [GM]iB)'),
            'GPU_free_memory': value(r'of which ([0-9.]+ [GM]iB) is free'),
            'pytorch_allocated': value(r'([0-9.]+ [GM]iB) is allocated by PyTorch'),
            'pytorch_reserved_unallocated': value(r'([0-9.]+ [GM]iB) is reserved by PyTorch but unallocated'),
            'prompt_token_min': min(row['prompt_tokens'] for row in matching),
            'prompt_token_max': max(row['prompt_tokens'] for row in matching)})
    frozen_error_documents = sum('error' in report for report in frozen_reports)
    return {'scope': 'Raw-frozen-response diagnostics; gold relations not opened or used',
        'documents': len(documents), 'response_status_counts': dict(Counter(row['status'] for row in responses.values())),
        'original_strict_rejection_reason_counts': dict(strict_reason_counts),
        'original_strict_error_documents': frozen_error_documents,
        'JSON_failures': [{'response_status': status, 'decoder_error': error, 'documents': count} for (status, error), count in raw_json.items()],
        'extra_data_suffix_classification_only': dict(tails), 'valid_JSON_wrong_top_schema': dict(top_schema),
        'JSON_and_generation_counts_overlap': 'All24 empty generation-error replies are included in the original156 JSON/top-schema failures; do not add them as disjoint counts.',
        'generation_errors': groups, 'generated_output_limit_documents': len(generated_limits),
        'generated_output_limit_pmids': generated_limits,
        'relation_rows_in_valid_top_schema_responses': total_rows,
        'invalid_evidence_span_rows': bad_span_rows,
        'invalid_span_offset_classification': dict(offsets),
        'invalid_span_exact_quote_occurrence_classification': dict(quotes),
        'invalid_span_unique_exact_quote_contains_both_correct_native_arguments': exact_quote_both,
        'invalid_span_native_entity_errors': dict(entity_errors),
        'invalid_span_provided_offsets_matching_entity_boundaries': dict(boundaries),
        'interpretation': 'Numeric-offset/quotation inconsistency is observed. Exact quotation alone does not establish the asserted relation label, entailment, causality or binding.',
        'no_JSON_or_quote_repair': True}


def run(args):
    root = args.root.resolve()
    source = root / 'data/drugprot_qwen_continuation_v1'
    base = root / 'data/drugprot/development'
    abstracts = base / 'drugprot_development_abstracts.tsv'
    entities = base / 'drugprot_development_entities.tsv'
    gold = base / 'drugprot_development_relations.tsv'
    responses_path = source / 'merged_responses.jsonl'
    summary_path = source / 'inference_summary.json'
    reports_path = source / 'validation_reports.json'
    lock_path = source / 'continuation_lock.json'
    frozen_paths = [abstracts, entities, responses_path, summary_path, reports_path, lock_path,
        source/'qwen_relations.tsv', source/'qwen_metrics.json',
        root/'src/nutriomics_evidence/extraction.py', root/'src/nutriomics_evidence/literature.py',
        root/'scripts/run_qwen.py', root/'scripts/run_literature_qwen.py']
    before = {str(path.relative_to(root)): sha(path) for path in frozen_paths}
    if before[str(abstracts.relative_to(root))] != NATIVE_SHA['abstracts'] or before[str(entities.relative_to(root))] != NATIVE_SHA['entities']:
        raise ValueError('Native corpus hash mismatch')
    summary = json.loads(summary_path.read_text(encoding='utf-8'))
    if sha(responses_path) != summary['responses_sha256'] or sha(lock_path) != summary['continuation_lock_sha256']:
        raise ValueError('Frozen inference receipt hash mismatch')
    documents = load_drugprot(abstracts, entities)
    raw = load_jsonl(responses_path)
    ordered_pmids = [document['pmid'] for document in documents]
    if len(documents) != 750 or len(raw) != 750 or [row['pmid'] for row in raw] != ordered_pmids or len(set(ordered_pmids)) != 750:
        raise ValueError('Require every native development PMID exactly once in native order')
    ordered_sha = hashlib.sha256(json.dumps(ordered_pmids).encode()).hexdigest()
    if ordered_sha != summary['coverage_audit']['ordered_pmids_sha256']:
        raise ValueError('Ordered corpus identity mismatch')
    responses = {row['pmid']: row for row in raw}
    frozen_reports = json.loads(reports_path.read_text(encoding='utf-8'))
    if len(frozen_reports) != 750 or [row['pmid'] for row in frozen_reports] != ordered_pmids:
        raise ValueError('Original validation-report coverage mismatch')
    out = args.out.resolve()
    if out.exists() or any(out == path or out in path.parents for path in frozen_paths + [gold]):
        raise ValueError('Diagnostic output must be a new directory outside frozen inputs')
    out.mkdir(parents=True)
    failure = failure_analysis(documents, responses, frozen_reports)
    if failure['invalid_evidence_span_rows'] != summary['rejection_reason_counts']['invalid_evidence_span'] or failure['original_strict_error_documents'] != summary['json_or_top_schema_error_documents']:
        raise ValueError('Failure analysis does not reproduce frozen strict counters')
    save(out/'failure_analysis.json', failure)
    relations, reports, errors, reasons = [], [], Counter(), Counter()
    for document in documents:
        raw_response = responses[document['pmid']]
        if raw_response['status'] != 'generated':
            errors['generation_error_abstention'] += 1
            reports.append({'pmid': document['pmid'], 'accepted': [], 'rejected': [], 'error': 'generation_error_abstention'})
            continue
        try:
            parsed = parse_quote_grounded(raw_response['response'], document)
        except (ValueError, TypeError, KeyError) as error:
            errors['invalid_JSON_or_top_level_schema'] += 1
            reports.append({'pmid': document['pmid'], 'accepted': [], 'rejected': [], 'error': str(error)})
            continue
        relations.extend(parsed['accepted'])
        for rejected in parsed['rejected']:
            reasons.update(rejected['reasons'])
        reports.append(parsed)
    save(out/'validation_reports.json', reports)
    save(out/'grounded_relations.json', relations)
    write_relations(out/'relations.tsv', relations)
    # Lock the label-free predictions before opening the reference relation file.
    lock = {'created_utc': datetime.now(timezone.utc).isoformat(), 'policy_version': POLICY_VERSION,
        'input_sha256': before, 'ordered_PMIDs_sha256': ordered_sha, 'documents': 750,
        'coverage': {'missing': 0, 'duplicate': 0, 'unexpected': 0},
        'parser_sha256': sha(root/'src/nutriomics_evidence/quote_grounding.py'),
        'script_sha256': sha(Path(__file__)), 'relations_sha256': sha(out/'relations.tsv'),
        'gold_relations_opened_for_grounding': False, 'parameters_selected_using_gold': False,
        'evaluation_status': 'Post-hoc development-set diagnostic after original strict results were exposed',
        'original_strict_inference_not_changed': True,
        'policy': 'Complete literal quote, unique globally, both native entity spans; unchanged strict gate; no JSON/whitespace/ID/label repair',
        'semantic_entailment_validated': False, 'generation_schema_evaluated': False, 'API_grounding_evaluated': False}
    save(out/'grounding_lock.json', lock)
    grounding_lock_sha = sha(out/'grounding_lock.json')
    # Gold is used only by the separate scoring stage below.
    if sha(gold) != NATIVE_SHA['gold']:
        raise ValueError('Frozen gold relation hash mismatch at scoring stage')
    strict_original = evaluate(gold, source/'qwen_relations.tsv', documents)
    if strict_original['micro'] != summary['qwen_micro']:
        raise ValueError('Original frozen strict score mismatch')
    score = evaluate(gold, out/'relations.tsv', documents)
    save(out/'metrics.json', score)
    changed = sum(row['grounding_receipt']['offsets_changed'] for row in relations)
    receipt = {**lock, 'grounding_lock_sha256': grounding_lock_sha,
        'accepted_relations': len(relations), 'accepted_with_reconstructed_offsets': changed,
        'rejected_relation_rows': sum(len(report['rejected']) for report in reports),
        'rejection_reason_counts': dict(reasons), 'document_error_counts': dict(errors),
        'original_strict_micro': strict_original['micro'], 'posthoc_diagnostic_strict_micro': score['micro'],
        'rule_frozen_micro': summary['rule_micro'],
        'gold_sha256_scoring_only': sha(gold), 'official_evaluation': {'status': 'not_run_in_this_script',
            'run_after_prediction_lock': True, 'original_upstream_indexing_unchanged': True},
        'full750_denominator': True, 'original_inputs_unchanged': all(sha(root/path) == digest for path, digest in before.items()),
        'binding_affinity': None, 'expert_approved_relation_count': None,
        'food_domain_accuracy': None, 'semantic_accuracy': None,
        'interpretation': 'Text grounding diagnostic only; fixed exact-quote recovery is not a new untouched test, tuned model, food-domain validation, validated schema, deployed API test or confirmed binding.'}
    if not receipt['original_inputs_unchanged']:
        raise ValueError('Frozen input or live extraction module changed during diagnostic')
    save(out/'diagnostic_receipt.json', receipt)
    docs = root/'docs'
    save(docs/'qwen_failure_analysis_v1.json', failure)
    save(docs/'qwen_quote_grounding_diagnostic_v1.json', receipt)
    failure_md = f'''# Frozen Qwen failure analysis\n\nThe full750 strict result remains unchanged: TP0, FP5, FN3761, F1=0. Numeric offset validity is distinct from textual or semantic relation support.\n\n- Invalid source spans: {failure['invalid_evidence_span_rows']} relation rows. Exact-quote occurrence categories: `{failure['invalid_span_exact_quote_occurrence_classification']}`.\n- Invalid-span rows with a unique exact quotation containing both correctly typed native argument spans: {failure['invalid_span_unique_exact_quote_contains_both_correct_native_arguments']}.\n- Original JSON/top-schema failures: {failure['original_strict_error_documents']} documents; includes24 empty generation-error responses. Counts overlap and must not be added.\n- Generation errors:24 documents in three batch8 CUDA out-of-memory groups. No model output exists for these documents; they remain abstentions.\n- Generated responses reaching the output limit: {failure['generated_output_limit_documents']}.\n\nAll measurements come from frozen raw responses and native source mentions, without opening reference relations in the diagnostic stage. Numeric and text grounding failures do not prove semantic accuracy. No JSON suffix, quotation, whitespace, ID or label repair is used. Raw quotations remain in ignored local data; this report publishes only counters and hashes.\n'''
    (docs/'qwen_failure_analysis_v1.md').write_text(failure_md, encoding='utf-8')
    micro = score['micro']
    diagnostic_md = f'''# Exact quotation grounding: separate post-hoc diagnostic\n\nThe original strict full750 score remains F1=0 (TP0/FP5/FN3761). This separate parser was developed after that score was exposed. It must not replace the original measurement or be represented as an untouched evaluation.\n\nThe supplied complete quotation must appear exactly once in unchanged source text and contain both native CHEMICAL/GENE argument spans. Its deterministic offsets then pass through the unchanged strict parser, including negation rejection. Original six JSON fields are supported; nullable numeric spans are a diagnostic accommodation. Generation-schema and API grounding validation have not been performed. Malformed/extra JSON, ambiguous quotation, missing quotation, wrong entities and unsupported labels abstain.\n\nAll750 documents remain in the denominator. Accepted relations: {len(relations)}; reconstructed offsets: {changed}. Strict exact tuple TP={micro['tp']}, FP={micro['fp']}, FN={micro['fn']}; precision={micro['precision']:.6f}, recall={micro['recall']:.6f}, F1={micro['f1']:.6f}. Official upstream scoring is a separate subsequent step because its known matrix-boundary indexing issue can change counts.\n\nGold relations were opened only after predictions and their grounding lock were written. Prediction SHA256: `{lock['relations_sha256']}`. Grounding lock SHA256: `{grounding_lock_sha}`. Semantic entailment, expert approval, food accuracy, binding affinity and therapeutic effect are unvalidated. Exact text grounding alone is not proof of the relation label or causality. No model training or gold-guided parameter search occurred.\n'''
    (docs/'qwen_quote_grounding_diagnostic_v1.md').write_text(diagnostic_md, encoding='utf-8')
    print(json.dumps({'documents': 750, 'accepted': len(relations), 'strict_micro': micro,
        'source_unchanged': receipt['original_inputs_unchanged'], 'output': str(out)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--out', type=Path, default=Path('data/quote_grounding_diagnostic_v1'))
    run(parser.parse_args())
