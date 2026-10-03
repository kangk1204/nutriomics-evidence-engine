"""Train the new lexical comparator on the official 3500-document train split.

Threshold is selected only on a document-disjoint 20% portion of train.
Previously inspected development 750 is retained as a post-hoc comparator,
with all gold relations counted, including those outside candidate windows.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import zipfile
import joblib
import numpy as np
from sklearn.model_selection import train_test_split
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from nutriomics_evidence.extraction import load_drugprot, read_relations, write_relations, evaluate
from nutriomics_evidence.supervised_relations import candidates, targets, fit, predict, export, tuple_scores


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def run(root, out):
    if out.exists():
        raise FileExistsError("A new experiment directory is required")
    out.mkdir(parents=True)
    archive = root / "data/drugprot/drugprot-training-development-test-background.zip"
    with archive.open("rb") as stream:
        if hashlib.file_digest(stream, "md5").hexdigest() != "c706ebf04580c3126154d96a43e64f2e":
            raise ValueError("Pinned official archive checksum differs")
    train_dir = root / "data/drugprot/training_supervised_v1"
    train_dir.mkdir(exist_ok=True)
    files = {}
    with zipfile.ZipFile(archive) as z:
        for member in z.infolist():
            name = Path(member.filename).name.replace("abstracs", "abstracts")
            if name in {f"drugprot_training_{kind}.tsv" for kind in ("abstracts", "entities", "relations")}:
                if name in files:
                    raise ValueError("Ambiguous training member")
                path = train_dir / name
                payload = z.read(member)
                if path.exists() and path.read_bytes() != payload:
                    raise ValueError("Prior training input changed")
                if not path.exists():
                    path.write_bytes(payload)
                files[name] = path
    if len(files) != 3:
        raise ValueError("Official training inputs incomplete")
    train = load_drugprot(files["drugprot_training_abstracts.tsv"], files["drugprot_training_entities.tsv"])
    dev = root / "data/drugprot/development"
    test = load_drugprot(dev / "drugprot_development_abstracts.tsv", dev / "drugprot_development_entities.tsv")
    if len(train) != 3500 or len(test) != 750:
        raise ValueError("Official corpus denominator changed")
    if {d["pmid"] for d in train} & {d["pmid"] for d in test}:
        raise ValueError("Training-development PMID overlap")
    if {hashlib.sha256(d["text"].encode()).hexdigest() for d in train} & {hashlib.sha256(d["text"].encode()).hexdigest() for d in test}:
        raise ValueError("Training-development exact text overlap")
    protocol = {"created_utc": datetime.now(timezone.utc).isoformat(), "seed": 20261003,
                "train_documents": 3500, "evaluation_documents": 750, "development_previously_examined": True,
                "model": "TF-IDF word 1/2-grams + one-vs-rest logistic SGD", "max_candidate_span": 800,
                "threshold_candidates": [.05, .1, .2, .3, .5, .7, .9], "threshold_fit_scope": "20% document holdout of official training only",
                "gold_mentions_used": True, "NER_or_food_accuracy_evaluated": False,
                "archive_sha256": digest(archive), "train_input_sha256": {k: digest(p) for k, p in files.items()},
                "source": "https://zenodo.org/records/5119892", "license": "Original corpus metadata/rights retained; raw archive and text not redistributed"}
    save(out / "protocol.json", protocol)
    gold_train = read_relations(files["drugprot_training_relations.tsv"])
    development_ids, validation_ids = train_test_split([d["pmid"] for d in train], test_size=.2, random_state=20261003)
    validation_ids = set(validation_ids)
    save(out / "training_split.json", {"fit_pmids": development_ids, "validation_pmids": sorted(validation_ids)})
    rows = [r for d in train for r in candidates(d)]
    a = [r for r in rows if r["pmid"] not in validation_ids]
    b = [r for r in rows if r["pmid"] in validation_ids]
    vectorizer, model = fit(a, targets(a, gold_train))
    probabilities = predict(b, vectorizer, model)
    validation_gold = {r for r in gold_train if r[0] in validation_ids}
    trials = [{"threshold": t, **tuple_scores(validation_gold, export(b, probabilities, t))} for t in protocol["threshold_candidates"]]
    best = max(trials, key=lambda r: r["f1"])
    save(out / "training_threshold_selection.json", {"all_trials": trials, "selected": best, "scope": "Official training-only document holdout"})
    print(json.dumps({"train_candidates": len(rows), "threshold": best}), flush=True)
    vectorizer, model = fit(rows, targets(rows, gold_train))
    test_rows = [r for d in test for r in candidates(d)]
    predicted = export(test_rows, predict(test_rows, vectorizer, model), best["threshold"])
    raw_dir = root / "results" / out.name
    raw_dir.mkdir(parents=True, exist_ok=False)
    save(raw_dir / "source_grounded_predictions.json", predicted)
    write_relations(raw_dir / "predictions.tsv", predicted)
    result = evaluate(dev / "drugprot_development_relations.tsv", raw_dir / "predictions.tsv", test)
    test_gold = read_relations(dev / "drugprot_development_relations.tsv")
    candidate_pairs = {(r["pmid"], r["arg1"], r["arg2"]) for r in test_rows}
    result.update(protocol=protocol, selected_threshold=best["threshold"], train_candidates=len(rows), evaluation_candidates=len(test_rows),
                  evaluation_gold_relations=len(test_gold), gold_relations_outside_candidates=sum((p, a, b) not in candidate_pairs for p, _, a, b in test_gold),
                  previous_baselines_preserved=True, gold_relations_in_features=False,
                  model_version="supervised-lexical-v1", final_result_scope="Post-hoc public development comparator; not food-domain or NER accuracy",
                  script_sha256=digest(Path(__file__)), prediction_tsv_sha256=digest(raw_dir / "predictions.tsv"))
    model_dir = root / "models" / out.name
    model_dir.mkdir(parents=True, exist_ok=False)
    joblib.dump({"vectorizer": vectorizer, "model": model, "threshold": best["threshold"]}, model_dir / "model.joblib")
    result["model_sha256"] = digest(model_dir / "model.joblib")
    save(out / "summary.json", result)
    print(json.dumps(result["micro"]), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    run(args.root, args.out)
