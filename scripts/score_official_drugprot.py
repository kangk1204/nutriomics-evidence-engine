#!/usr/bin/env python3
"""Run the pinned, unchanged official DrugProt evaluator on immutable copies.

The upstream CLI prints three decimal places and returns None. A child-process
observer calls the original metric function, then measures the very same arrays
at full precision. It never changes their construction or repairs upstream code.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

REPO_URL = "https://github.com/tonifuc3m/drugprot-evaluation-library"
COMMIT = "6b939554de38dbb69c462cc0d45c1cb17c3eaf57"
BLOBS = {
    "src/main.py": "23618a0c83c2916db2115c0cbf7c1084bc149dd04c48fadae6f4fddff5fc4b96",
    "src/utils.py": "fd6cc42a35005720f22b890a4fdeed54bea2dd8396e36edad2eccf1140e9ae1b",
    "src/compute_metrics.py": "c15fdccc6d96435813b32ce6eeda91a3ac16bb4b3a5bb1eff9425fe62c9e8ac3",
    "LICENSE": "94f14b3e1c664e01efb64cccc1fafe647ba35ba7849bdc5d9849a10fedf0813c",
    "README.md": "d6ae8808bd59934a42fc822948ce12bf006c2c0f00f18a2e528ff5b958833af9",
    "requirements.txt": "edce0dff6a598f9ad2322cccf7c7ca338c91a7e4e7a365cbcf21521bf3c19717",
}
NATIVE_SHA = {
    "abstracts": "dc9a9deb6c4e37bc67380b888718689f3f11edc4e09de838891674d6565d89b8",
    "entities": "212c88668c611edf067ae39f052494febbb8dcb2fc81af8160507a4a176c667e",
    "gold": "6df63c08a7e1ae50d9bf32a2c91eeec641e9b879cfd3b1a4cec15b0b2781403d",
}
RELATIONS = {
    "ACTIVATOR", "AGONIST", "AGONIST-ACTIVATOR", "AGONIST-INHIBITOR",
    "ANTAGONIST", "DIRECT-REGULATOR", "INDIRECT-DOWNREGULATOR",
    "INDIRECT-UPREGULATOR", "INHIBITOR", "PART-OF", "PRODUCT-OF",
    "SUBSTRATE", "SUBSTRATE_PRODUCT-OF",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def tsv(path: Path):
    # DrugProt text is literal TSV. In particular, do not strip literal quotes.
    with path.open(encoding="utf-8", newline="") as handle:
        yield from csv.reader(handle, delimiter="\t", quoting=csv.QUOTE_NONE)


def verify_library(path: Path) -> dict:
    head = subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()
    if head != COMMIT:
        raise ValueError(f"Official evaluator commit mismatch: {head}")
    files = {}
    for name, expected in BLOBS.items():
        blob = subprocess.check_output(["git", "-C", str(path), "show", COMMIT + ":" + name])
        raw = (path / name).read_bytes()
        if hashlib.sha256(blob).hexdigest() != expected or raw.replace(b"\r\n", b"\n") != blob:
            raise ValueError(f"Official source changed: {name}")
        files[name] = {"git_blob_sha256": expected, "working_tree_sha256": sha(path / name)}
    return {"url": REPO_URL, "commit": head, "license": "MIT", "files": files}


def validate_corpus(abstracts: Path, entities: Path, gold: Path, predictions: Path) -> tuple[list[str], dict]:
    for key, path in [("abstracts", abstracts), ("entities", entities), ("gold", gold)]:
        if sha(path) != NATIVE_SHA[key]:
            raise ValueError(f"Frozen official development source hash mismatch: {key}")
    docs = {}
    for row in tsv(abstracts):
        if len(row) != 3 or not row[0].isdigit() or row[0] in docs:
            raise ValueError("Malformed or duplicate development abstract")
        docs[row[0]] = row[1] + " " + row[2]
    if len(docs) != 750:
        raise ValueError("This protocol requires exactly 750 official development PMIDs")
    lookup = {}
    for row in tsv(entities):
        if len(row) != 6 or row[0] not in docs:
            raise ValueError("Malformed or out-of-scope entity")
        pmid, identifier, kind, start, end, text = row
        start, end = int(start), int(end)
        if ((pmid, identifier) in lookup or kind not in {"CHEMICAL", "GENE"}
                or not 0 <= start < end <= len(docs[pmid]) or docs[pmid][start:end] != text):
            raise ValueError("Duplicate entity or native type/span mismatch")
        lookup[(pmid, identifier)] = kind

    def relations(path: Path) -> set:
        result = set()
        for row in tsv(path):
            if len(row) != 4 or row[0] not in docs or row[1] not in RELATIONS:
                raise ValueError(f"Malformed, unsupported, or unexpected PMID relation: {path}")
            if not row[2].startswith("Arg1:") or not row[3].startswith("Arg2:"):
                raise ValueError("Relation argument direction must be explicit")
            key = (row[0], row[1], row[2][5:], row[3][5:])
            if key in result:
                raise ValueError("Duplicate relation tuple")
            if lookup.get((key[0], key[2])) != "CHEMICAL" or lookup.get((key[0], key[3])) != "GENE":
                raise ValueError("Relation requires native CHEMICAL Arg1 and GENE Arg2")
            result.add(key)
        return result

    expected, observed = relations(gold), relations(predictions)
    return list(docs), {"documents": len(docs), "entities": len(lookup), "gold_relations": len(expected),
                        "predicted_relations": len(observed), "micro": exact_metrics(expected, observed),
                        "scope": "strict exact tuples with native, directed gold entity IDs"}


def exact_metrics(expected: set, observed: set) -> dict:
    tp, fp, fn = len(expected & observed), len(observed - expected), len(expected - observed)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall,
            "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0}


def parse_stdout(value: str) -> dict:
    result = {}
    for upstream, label in [("p_micro", "precision"), ("r_micro", "recall"), ("f1_micro", "f1")]:
        matches = re.findall(r"^" + upstream + r"=([0-9.]+)$", value, re.MULTILINE)
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one official {upstream} output")
        result[label] = float(matches[0])
    return result


def driver(args) -> None:
    # This process uses the unmodified official main() and metric function.
    sys.path.insert(0, str(args.library / "src"))
    import main as upstream
    import compute_metrics as upstream_metrics
    from sklearn.metrics import f1_score, precision_score, recall_score
    original = upstream_metrics.main

    def observer(y_true, y_pred, reltype2tag, gs_rel_list, pred_rel_list):
        returned = original(y_true, y_pred, reltype2tag, gs_rel_list, pred_rel_list)
        tp = sum(bool(a) and bool(b) for rt, rp in zip(y_true, y_pred) for a, b in zip(rt, rp))
        fp = sum(not bool(a) and bool(b) for rt, rp in zip(y_true, y_pred) for a, b in zip(rt, rp))
        fn = sum(bool(a) and not bool(b) for rt, rp in zip(y_true, y_pred) for a, b in zip(rt, rp))
        result = {
            "micro": {"tp": tp, "fp": fp, "fn": fn,
                      "precision": float(precision_score(y_true, y_pred, average="micro")),
                      "recall": float(recall_score(y_true, y_pred, average="micro")),
                      "f1": float(f1_score(y_true, y_pred, average="micro"))},
            "upstream_metric_returned_none": returned is None,
            "matrix_shape": [len(y_true), len(y_true[0])],
            "capture_method": "post-call observation of the unchanged official matrices; no index repair",
        }
        save(args.output / "official_exact_metrics.json", result)
        return returned

    upstream_metrics.main = observer
    namespace = argparse.Namespace(gs_path=str(args.gold), ent_path=str(args.entities),
                                   pred_path=str(args.predictions), pmids=str(args.output / "pmids.txt"))
    upstream.main(namespace)


def run(args) -> int:
    args.library = args.library.resolve()
    input_paths = {k: getattr(args, k).resolve() for k in ["abstracts", "entities", "gold", "predictions"]}
    source = verify_library(args.library)
    pmids, strict = validate_corpus(**input_paths)
    if args.custom_metrics:
        previous = json.loads(args.custom_metrics.read_text(encoding="utf-8"))["micro"]
        if any(abs(previous[k] - strict["micro"][k]) > 1e-12 for k in strict["micro"]):
            raise ValueError("Existing custom metrics do not match strict input re-evaluation")
    args.output = args.output.resolve()
    if args.output.exists():
        raise ValueError("Output must be a new directory: evaluation records are never overwritten")
    if any(p == args.output or args.output in p.parents for p in input_paths.values()):
        raise ValueError("Native inputs must stay outside the new evaluation output")
    input_hashes = {k: {"path": str(p), "sha256": sha(p)} for k, p in input_paths.items()}
    args.output.mkdir(parents=True)
    for key, path in input_paths.items():
        shutil.copyfile(path, args.output / (key + ".tsv"))
    (args.output / "pmids.txt").write_text("".join(p + "\n" for p in pmids), encoding="utf-8")
    copies = {k: sha(args.output / (k + ".tsv")) for k in input_paths}
    report = {"started_utc": datetime.now(timezone.utc).isoformat(), "official_source": source,
              "input_files": input_hashes, "immutable_copy_sha256": copies,
              "pmids_sha256": sha(args.output / "pmids.txt"), "strict_custom": strict,
              "wrapper_sha256": sha(Path(__file__)),
              "environment": {"python": sys.version, "executable": sys.executable,
                              **{n: importlib.metadata.version(n) for n in ["numpy", "pandas", "scikit-learn", "scipy"]}},
              "gold_mentions_used": True, "evaluation_scope": "development 750 relation extraction, not NER",
              "source_caveat": "Upstream format_relations advances pos0 by idx (len(combs)-1); preserve this behavior"}
    save(args.output / "evaluation_lock.json", report)
    command = [sys.executable, str(Path(__file__).resolve()), "--_driver", "--library", str(args.library),
               "--abstracts", str(args.output / "abstracts.tsv"), "--entities", str(args.output / "entities.tsv"),
               "--gold", str(args.output / "gold.tsv"), "--predictions", str(args.output / "predictions.tsv"),
               "--output", str(args.output)]
    env = dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1")
    started = time.monotonic()
    try:
        with (args.output / "stdout.txt").open("w", encoding="utf-8") as stdout, (args.output / "stderr.txt").open("w", encoding="utf-8") as stderr:
            completed = subprocess.run(command, env=env, stdout=stdout, stderr=stderr, timeout=args.timeout, check=False)
        report.update(exit_code=completed.returncode, elapsed_seconds=time.monotonic() - started,
                      status="completed" if completed.returncode == 0 else "official_execution_failed")
    except subprocess.TimeoutExpired:
        report.update(exit_code=None, elapsed_seconds=time.monotonic() - started, status="official_execution_timeout")
    report["command"] = command
    report["original_inputs_unchanged"] = all(sha(input_paths[k]) == d["sha256"] for k, d in input_hashes.items())
    report["immutable_copies_unchanged"] = all(sha(args.output / (k + ".tsv")) == h for k, h in copies.items())
    report["official_source_unchanged"] = verify_library(args.library) == source
    if not all(report[k] for k in ["original_inputs_unchanged", "immutable_copies_unchanged", "official_source_unchanged"]):
        report["status"] = "immutability_failure"
    if report["status"] == "completed":
        printed = parse_stdout((args.output / "stdout.txt").read_text(encoding="utf-8"))
        official = json.loads((args.output / "official_exact_metrics.json").read_text(encoding="utf-8"))
        report["official_stdout_micro_rounded_3dp"] = printed
        report["official_same_matrix_full_precision"] = official
        if any(round(official["micro"][k], 3) != v for k, v in printed.items()):
            raise ValueError("Official CLI print and observed full precision disagree")
        report["comparison"] = {
            "exact_parity": all(abs(strict["micro"][k] - official["micro"][k]) <= 1e-12 for k in strict["micro"]),
            "custom_minus_official": {k: strict["micro"][k] - official["micro"][k] for k in strict["micro"]},
            "no_upstream_patches": True,
        }
    report["completed_utc"] = datetime.now(timezone.utc).isoformat()
    for name in ["stdout.txt", "stderr.txt", "official_exact_metrics.json"]:
        if (args.output / name).exists():
            report.setdefault("output_sha256", {})[name] = sha(args.output / name)
    save(args.output / "evaluation_report.json", report)
    print(json.dumps({"status": report["status"], "output": str(args.output), "comparison": report.get("comparison")}))
    return 0 if report["status"] == "completed" else 1


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, default=Path("data/reference_drugprot_eval"))
    base = Path("data/drugprot/development")
    parser.add_argument("--abstracts", type=Path, default=base / "drugprot_development_abstracts.tsv")
    parser.add_argument("--entities", type=Path, default=base / "drugprot_development_entities.tsv")
    parser.add_argument("--gold", type=Path, default=base / "drugprot_development_relations.tsv")
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--custom-metrics", type=Path)
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--_driver", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


if __name__ == "__main__":
    selected = arguments()
    if selected._driver:
        driver(selected)
    else:
        raise SystemExit(run(selected))
