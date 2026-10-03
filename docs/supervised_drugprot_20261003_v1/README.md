Supervised DrugProt comparator, 2026-10-03
========================================

The new CPU comparator trains TF-IDF word 1/2-grams and one-vs-rest logistic SGD
on the official 3,500-document training corpus. Its threshold is selected on a
20% document holdout of training only. Evaluation covers all 750 development
documents and all 13 native relations; provided gold entity spans are required.
This is not a food NER or Qwen model accuracy result. Development has already
been inspected by earlier methods, so this comparison is explicitly post hoc.

Strict tuple micro precision .260519, recall .266684, F1 .263566 (TP1003,
FP2847, FN2758; 3761 gold relations). The unchanged upstream evaluator gives
F1 .264141 with TP1004/FP2840/FN2754 and 3758 gold. The exact discrepancy is
preserved in official_evaluation.json, not hidden behind rounded equality.
Training/development PMID and exact text hash overlap are zero. Raw training
texts, predictions with source quotes and model weights stay in ignored folders.

Reproduction: scripts/run_supervised_drugprot.py and the official evaluator
script use the pinned archive/source hashes in protocol.json/summary.json.
Full selected graph row auditing is independent of extraction accuracy and is
recorded in docs/graph_allrow_20261003_v3.json. Source-reported CTD identifier
bridges are not exact molecular structure links, measured Kd or food efficacy.
