import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import pytest

SCRIPT = Path(__file__).resolve().parents[1]/'scripts/retry_literature_oom.py'
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location('retry_literature_oom', SCRIPT)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def fixture():
    selected = set(runner.OOM_PMIDS)
    pmids = runner.OOM_PMIDS + [str(90000000+i) for i in range(1190)]
    documents, records = [], []
    for number, pmid in enumerate(pmids):
        eligible = number < 202
        reason = None if eligible else 'no_unambiguous_chemical_gene_document_comention'
        documents.append({'pmid': pmid, 'qwen_eligible': eligible, 'abstention_reason': reason})
        records.append({'pmid': pmid, 'status': 'generation_error' if pmid in selected else 'generated' if eligible else 'no_comention_abstention',
            'response': '' if pmid in selected else '{"relations": []}',
            **({'error': 'CUDA out of memory. Actual frozen error.'} if pmid in selected else {}),
            **({'reason': reason, 'model_invoked': False} if not eligible else {})})
    return documents, records


def test_selects_only_eight_actual_oom_records_in_native_order():
    documents, records = fixture()
    assert [d['pmid'] for d in runner.select_oom_documents(documents, list(reversed(records)))] == runner.OOM_PMIDS
    assert runner.SETTINGS['batch_size'] == 1 and runner.SETTINGS['seed'] == 42
    assert runner.SETTINGS['do_sample'] is False and runner.SETTINGS['trust_remote_code'] is False


@pytest.mark.parametrize('change', ['foreign', 'missing', 'duplicate'])
def test_changed_source_coverage_is_rejected(change):
    documents, records = fixture()
    if change == 'foreign':records[0]['pmid'] = '777'
    elif change == 'missing':records.pop()
    else:records[-1]['pmid'] = records[0]['pmid']
    with pytest.raises(ValueError, match='coverage/cohort'):
        runner.select_oom_documents(documents, records)


@pytest.mark.parametrize('changes', [{'error': 'some other error'}, {'response': '{}'}, {'status': 'missing_response'}])
def test_missing_or_other_error_is_not_relabelled_as_an_oom_retry(changes):
    documents, records = fixture();records[0].update(changes)
    with pytest.raises(ValueError):runner.select_oom_documents(documents, records)


def test_explicit_abstention_tamper_is_rejected():
    documents, records = fixture();records[-1]['model_invoked'] = True
    with pytest.raises(ValueError, match='abstention'):
        runner.select_oom_documents(documents, records)


def test_retry_pmid_selection_changes_are_rejected():
    documents, records = fixture()
    with pytest.raises(ValueError, match='eight OOM'):
        runner.select_oom_documents(documents, records, expected_pmids=runner.OOM_PMIDS[:-1]+['999'])


def fake_torch(*, available=True, count=1, name=runner.GPU_NAME, free=12*1024**3):
    return SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: available, device_count=lambda: count,
        get_device_name=lambda _: name, mem_get_info=lambda _: (free,16*1024**3)))


@pytest.mark.parametrize('params', [{'available': False}, {'count': 2}, {'name': 'NVIDIA H200'}, {'free': 1024}])
def test_no_cpu_h200_multiple_gpu_or_low_memory_fallback(params):
    with pytest.raises(RuntimeError):runner.check_cuda(fake_torch(**params))


def test_authorized_single_gpu_preflight_has_explicit_policy():
    value = runner.check_cuda(fake_torch())
    assert value['routing_authorized_endpoint'] == '100.84.183.6' and value['H200_allowed'] is False


def test_new_run_is_locked_and_cannot_be_overwritten_or_reexecuted(tmp_path):
    out = tmp_path/'run';config = {'batch_size': 1, 'source_sha': 'frozen', 'pmids': runner.OOM_PMIDS}
    runner.preserve_new_run(out, config)
    assert json.loads((out/'retry_lock.json').read_text()) == config
    with pytest.raises(FileExistsError):runner.preserve_new_run(out, config)
    changed = {**config, 'batch_size': 8}
    with pytest.raises(ValueError, match='Frozen retry parameters'):
        runner.preserve_new_run(out, changed)
    changed = {**config, 'source_sha': 'changed'}
    with pytest.raises(ValueError):runner.preserve_new_run(out, changed)
    assert json.loads((out/'retry_lock.json').read_text()) == config


def test_source_response_byte_hash_tamper_rejected_before_model_access(tmp_path):
    root = tmp_path/'isolated';inference = root/'data/literature_qwen_v1';inference.mkdir(parents=True)
    (inference/'responses.jsonl').write_bytes(b'tampered')
    with pytest.raises(ValueError, match='response SHA'):
        runner.source_configuration(root,root/'prepared',inference,root/'model',root/'model_lock.json',root/'out')


def test_paths_outside_isolated_checkout_are_rejected_before_any_model_access(tmp_path):
    root = tmp_path/'isolated'
    with pytest.raises(ValueError, match='isolated evidence'):
        runner.source_configuration(root,root/'prepared',root/'inference',tmp_path/'outside_model',root/'lock',root/'out')


def test_physical_jsonl_does_not_split_unicode_source_lines():
    raw = (json.dumps({'text':'a\u2028b'},ensure_ascii=False)+'\n').encode()
    assert runner.read_jsonl_bytes(raw) == [{'text':'a\u2028b'}]
