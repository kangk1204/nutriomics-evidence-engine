"""Continuation integrity tests use synthetic fixtures, never benchmark scores."""
import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("qwen_continuation_under_test", SCRIPTS / "run_qwen_continuation.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def record(pmid, response='{"relations": []}'):
    return {"pmid": pmid, "status": "generated", "response": response}


def write_rows(path, rows):
    path.write_bytes("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows).encode())


def checkpoint_fixture(tmp_path):
    original = tmp_path / "original"
    original.mkdir()
    abstracts, entities = tmp_path / "abstracts.tsv", tmp_path / "entities.tsv"
    abstracts.write_text("literal source abstracts", encoding="utf8")
    entities.write_text("literal source entities", encoding="utf8")
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    weight = model_dir / "weights.safetensors"
    weight.write_bytes(b"synthetic integrity-test weight bytes; never loaded as a model")
    model_lock_path = tmp_path / "model_lock.json"
    model_lock = {"repo_id": module.MODEL, "commit": "a" * 40,
                  "files": [{"path": weight.name, "bytes": weight.stat().st_size, "sha256": module.digest(weight)}]}
    model_lock_path.write_text(json.dumps(model_lock), encoding="utf8")
    documents = [{"pmid": str(index), "text": "Title. Literal source text.", "entities": []} for index in range(1, 751)]
    prompts = {document["pmid"]: module.messages_with_sentence_offsets(document) for document in documents}
    lock = {"repo_id": "Qwen/Qwen2.5-7B-Instruct", "commit": "a" * 40,
            "model_lock_sha256": module.digest(model_lock_path), "abstracts_sha256": module.digest(abstracts),
            "entities_sha256": module.digest(entities), "gold_sha256": None,
            "prompt_sha256": hashlib.sha256(json.dumps(prompts, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
            "script_sha256": module.digest(SCRIPTS / "run_qwen.py"), "batch_size": 4,
            "max_input_tokens": 8192, "max_new_tokens": 1024, "do_sample": False, "seed": 42,
            "quantization": "bitsandbytes NF4 4bit double quantization, BF16 computation", "no_finetuning": True,
            "prompt_policy": "unchanged existing schema prompt plus exact sentence candidates/offsets",
            "selection": "all 750 dev documents; errors remain abstentions; prompts never include gold relations"}
    (original / "inference_lock.json").write_text(json.dumps(lock), encoding="utf8")
    write_rows(original / "responses.jsonl", [record(str(index)) for index in range(1, 5)])
    args = SimpleNamespace(original_out=original, out=tmp_path / "continuation", model_dir=model_dir,
                           model_lock=model_lock_path, abstracts=abstracts, entities=entities, gold=None)
    return args, documents, prompts, model_lock


def test_physical_lf_preserves_unicode_paragraph_separator_and_rejects_truncated_line(tmp_path):
    path = tmp_path / "responses.jsonl"
    value = '{"relations": [], "source": "alpha\u2028beta"}'
    write_rows(path, [record("1", value)])
    assert module.read_responses(path, {"1"})["1"]["response"] == value
    path.write_bytes(path.read_bytes().rstrip(b"\n"))
    with pytest.raises(ValueError, match="complete LF"):
        module.read_responses(path, {"1"})


@pytest.mark.parametrize("rows,cohort", [([record("1"), record("1")], {"1"}), ([record("unexpected")], {"1"})])
def test_jsonl_duplicate_or_unexpected_pmids_fail(tmp_path, rows, cohort):
    path = tmp_path / "responses.jsonl"
    write_rows(path, rows)
    with pytest.raises(ValueError, match="Duplicate or unexpected"):
        module.read_responses(path, cohort)


def test_exact750_merge_has_zero_duplicates_and_preserves_original_records():
    cohort = [str(index) for index in range(1, 751)]
    original = {pmid: record(pmid) for pmid in cohort[:200]}
    frozen = copy.deepcopy(original)
    residual = {pmid: record(pmid) for pmid in cohort[200:]}
    merged = module.merge_responses(original, residual, cohort)
    assert len(merged) == 750 and set(merged) == set(cohort)
    assert original == frozen
    with pytest.raises(ValueError, match="overlap"):
        module.merge_responses(original, {**residual, "1": record("1")}, cohort)
    with pytest.raises(ValueError, match="exact cohort"):
        module.merge_responses(original, {key: value for key, value in residual.items() if key != "750"}, cohort)
    with pytest.raises(ValueError, match="unexpected"):
        module.merge_responses(original, {**residual, "751": record("751")}, cohort)


def test_checkpoint_hash_validation_is_readonly_and_pending_source_order_is_unchanged(tmp_path):
    args, documents, prompts, _ = checkpoint_fixture(tmp_path)
    prior = {path.name: path.read_bytes() for path in args.original_out.iterdir()}
    verified_model = module.verify_model(args.model_dir, args.model_lock)
    _, snapshot, original, pending = module.validate_checkpoint(args, documents, prompts, verified_model)
    assert len(original) == 4 and pending == [str(index) for index in range(5, 751)]
    assert {path.name: path.read_bytes() for path in args.original_out.iterdir()} == prior
    assert not args.out.exists()
    module.assert_original_unchanged(args, snapshot)
    with (args.original_out / "responses.jsonl").open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(ValueError, match="Original artifact changed"):
        module.assert_original_unchanged(args, snapshot)


def test_source_or_prompt_hash_change_is_rejected_before_any_continuation_write(tmp_path):
    args, documents, prompts, model_lock = checkpoint_fixture(tmp_path)
    with args.abstracts.open("a", encoding="utf8") as stream:
        stream.write(" changed source")
    with pytest.raises(ValueError, match="abstracts_sha256"):
        module.validate_checkpoint(args, documents, prompts, model_lock)
    assert not args.out.exists()


def test_model_weight_mutation_is_rejected(tmp_path):
    args, _, _, _ = checkpoint_fixture(tmp_path)
    weight = args.model_dir / "weights.safetensors"
    weight.write_bytes(weight.read_bytes().replace(b"synthetic", b"different"))
    with pytest.raises(ValueError, match="Model file changed"):
        module.verify_model(args.model_dir, args.model_lock)


def test_frozen_continuation_artifact_byte_hash_change_is_rejected(tmp_path):
    lock = tmp_path / "continuation_lock.json"
    lock.write_bytes(b'{"batch_size": 8}\n')
    seal = {lock.name: module.digest(lock)}
    module.assert_continuation_locks_unchanged(tmp_path, seal)
    lock.write_bytes(b'{ "batch_size": 8 }\n')
    with pytest.raises(ValueError, match="Frozen continuation artifact changed"):
        module.assert_continuation_locks_unchanged(tmp_path, seal)


def test_checkpoint_prefix_score_guard_and_original_output_protection(tmp_path):
    args, documents, prompts, model_lock = checkpoint_fixture(tmp_path)
    write_rows(args.original_out / "responses.jsonl", [record("1"), record("2"), record("3"), record("750")])
    with pytest.raises(ValueError, match="source-order batch4 prefix"):
        module.validate_checkpoint(args, documents, prompts, model_lock)
    write_rows(args.original_out / "responses.jsonl", [record(str(index)) for index in range(1, 5)])
    (args.original_out / "qwen_metrics.json").write_text("not inspected", encoding="utf8")
    with pytest.raises(ValueError, match="precede original cohort score"):
        module.validate_checkpoint(args, documents, prompts, model_lock)
    args.out = args.original_out / "nested_output"
    with pytest.raises(ValueError, match="separate directory"):
        module.validate_checkpoint(args, documents, prompts, model_lock)
