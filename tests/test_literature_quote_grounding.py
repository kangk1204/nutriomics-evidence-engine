import hashlib
import importlib.util
import json
from pathlib import Path
import pytest

SCRIPT = Path(__file__).resolve().parents[1]/'scripts/ground_literature_quotes.py'
SPEC = importlib.util.spec_from_file_location('ground_literature_quotes', SCRIPT)
grounder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(grounder)


def fixture():
    text = 'Aspirin inhibits PTGS2.'
    candidate = {'pmid': '1', 'text': text, 'text_sha256': hashlib.sha256(text.encode()).hexdigest(),
        'qwen_eligible': True, 'abstention_reason': None,
        'source': {'source_url': 'https://pubmed.ncbi.nlm.nih.gov/1/', 'doi': 'example', 'pmcid': None, 'topics': ['HTN']},
        'entities': [
            {'id': 'T1', 'type': 'CHEMICAL', 'start': 0, 'end': 7, 'text': 'Aspirin', 'normalized_ids': ['MESH:D001241']},
            {'id': 'T2', 'type': 'GENE', 'start': 17, 'end': 22, 'text': 'PTGS2', 'normalized_ids': ['NCBIGene:5743']}]}
    skipped = {'pmid': '2', 'text': 'No scoped mentions.', 'qwen_eligible': False,
        'abstention_reason': 'no_unambiguous_chemical_gene_document_comention', 'entities': []}
    response = {'pmid': '1', 'status': 'generated', 'response': json.dumps({'relations': [
        {'relation': 'INHIBITOR', 'arg1': 'T1', 'arg2': 'T2', 'evidence_text': text, 'evidence_start': 0, 'evidence_end': 7}]})}
    abstention = {'pmid': '2', 'status': 'no_comention_abstention', 'response': grounder.EMPTY_RESPONSE,
        'reason': skipped['abstention_reason'], 'model_invoked': False}
    lock = {'documents': 2, 'eligible_documents': 1, 'gold_available': False}
    return [candidate, skipped], [response, abstention], lock


def validate(documents, records, lock):
    return grounder.validate_cohort(documents, records, lock, expected_documents=2, expected_eligible=1)


def test_grounded_candidates_keep_provenance_candidate_ids_and_pending_semantics():
    documents, records, lock = fixture()
    responses = validate(documents, records, lock)
    candidates, reports, counts = grounder.grounding_candidates(documents, responses)
    assert len(reports) == 2 and len(candidates) == 1
    row = candidates[0]
    assert row['subject_candidate_ids'] == ['MESH:D001241'] and row['object_candidate_ids'] == ['NCBIGene:5743']
    assert row['pmid'] == '1' and row['source_url'] == 'https://pubmed.ncbi.nlm.nih.gov/1/'
    assert row['source_text_sha256'] == documents[0]['text_sha256']
    assert row['expert_review_status'] == 'pending' and row['semantic_entailment_validated'] is False
    assert row['dictionary_NER_validated'] is False and row['clinical_efficacy'] is None and row['binding_affinity'] is None
    assert counts['original_strict_accepted_rows'] == 0
    assert counts['response_status_counts'] == {'generated': 1, 'no_comention_abstention': 1}


def test_foreign_cohort_is_rejected_instead_of_silently_ignored():
    documents, records, lock = fixture();records[0]['pmid'] = '999'
    with pytest.raises(ValueError, match='different cohort'):
        validate(documents, records, lock)


def test_missing_response_is_not_converted_to_generation_error_or_scoped_abstention():
    documents, records, lock = fixture()
    with pytest.raises(ValueError, match='Missing frozen response'):
        validate(documents, records[1:], lock)


def test_explicit_generation_error_is_retained_as_error_not_missing_response():
    documents, records, lock = fixture()
    records[0] = {'pmid': '1', 'status': 'generation_error', 'response': '', 'error': 'CUDA out of memory'}
    candidates, reports, counts = grounder.grounding_candidates(documents, validate(documents, records, lock))
    assert not candidates and counts['document_error_counts']['generation_error_abstention'] == 1
    assert reports[0]['status'] == 'generation_error' and reports[0]['not_missing_response'] is True


@pytest.mark.parametrize('changes', [{'response': '{}'}, {'status': 'generated'}, {'model_invoked': True}, {'reason': 'different'}])
def test_uninvoked_empty_abstention_cannot_be_tampered(changes):
    documents, records, lock = fixture();records[1].update(changes)
    with pytest.raises(ValueError, match='original explicit'):
        validate(documents, records, lock)


@pytest.mark.parametrize('changes', [{'error': ''}, {'response': '{"relations": []}'}, {'error': None}])
def test_error_receipt_is_required_for_generation_error(changes):
    documents, records, lock = fixture()
    records[0] = {'pmid': '1', 'status': 'generation_error', 'response': '', 'error': 'actual error', **changes}
    with pytest.raises(ValueError, match='actual error receipt'):
        validate(documents, records, lock)


@pytest.mark.parametrize('changes', [{'documents': 3}, {'eligible_documents': 2}, {'gold_available': True}])
def test_inference_cohort_or_gold_contract_mismatch_is_rejected(changes):
    documents, records, lock = fixture();lock.update(changes)
    with pytest.raises(ValueError, match='inference-lock'):
        validate(documents, records, lock)


def test_frozen_response_bytes_must_match_expected_hash(tmp_path):
    path = tmp_path/'responses.jsonl';path.write_bytes(b'original')
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    path.write_bytes(b'changed')
    with pytest.raises(ValueError, match='hash mismatch'):
        grounder.read_verified(path, expected)


def test_preparation_source_and_code_versions_must_match_inference_lock(tmp_path):
    preparation = {'files': {'documents.jsonl': 'documents_hash'}, 'module_sha256': 'module_hash'}
    raw = json.dumps(preparation).encode()
    code = tmp_path/'code.py';code.write_bytes(b'frozen')
    lock = {'preparation_lock_sha256': grounder.digest_bytes(raw), 'documents_sha256': 'documents_hash',
        'literature_module_sha256': 'module_hash', 'script_sha256': grounder.digest(code)}
    grounder.validate_inference_sources(lock, raw, preparation, code_files={'script_sha256': code})
    for key in lock:
        altered = {**lock, key: 'changed'}
        with pytest.raises(ValueError):
            grounder.validate_inference_sources(altered, raw, preparation, code_files={'script_sha256': code})


def test_malformed_generated_json_abstains_without_guessing():
    documents, records, lock = fixture();records[0]['response'] = '{"relations": []}```'
    candidates, reports, counts = grounder.grounding_candidates(documents, validate(documents, records, lock))
    assert not candidates and counts['document_error_counts']['generated_invalid_JSON_or_schema_abstention'] == 1
    assert reports[0]['status'] == 'generated'


def test_physical_jsonl_preserves_unicode_line_separator_in_source():
    raw = (json.dumps({'text': 'literal\u2028source'}, ensure_ascii=False)+'\n').encode()
    assert grounder.jsonl_bytes(raw) == [{'text': 'literal\u2028source'}]
