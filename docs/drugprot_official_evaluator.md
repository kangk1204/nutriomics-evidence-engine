# Official DrugProt evaluator: pinned independent check

The [official BioCreative VII DrugProt evaluation library](https://github.com/tonifuc3m/drugprot-evaluation-library) was actually cloned into the ignored directory `data/reference_drugprot_eval` on 2026-10-01. The pinned commit is `6b939554de38dbb69c462cc0d45c1cb17c3eaf57`, dated 2022-01-04. Its [MIT license](https://github.com/tonifuc3m/drugprot-evaluation-library/blob/6b939554de38dbb69c462cc0d45c1cb17c3eaf57/LICENSE) names Antonio Miranda-Escalada, copyright 2021. Retain that notice when copying or redistributing substantial source. The clone is a reference dependency; upstream tracked files remain unchanged.

The original evaluator accepts four-column relation TSV, gold entities and a PMID list. It prints micro and per-relation precision, recall and F1 rounded to three decimal places; `main()` and its metric function return `None`. It does not return a metrics dictionary. This behavior was confirmed by source inspection and an actual CLI execution.

From the evaluator directory, its documented example is:

```bash
cd src
python main.py -g ../gs-data/gs_relations.tsv -p ../toy-data/pred_relations.tsv \
  -e ../gs-data/gs_entities.tsv --pmids ../gs-data/pmids.txt
```

This project instead uses the actual [official development corpus v1.2](https://zenodo.org/records/5119892): exactly 750 unique PMIDs, 18,858 gold entity mentions and 3,761 unique gold relations. The provider's `abstracs` filename typo is normalized with the archive-member provenance retained. All three native file SHA256 values are mandatory in the wrapper. Native entity spans are checked against title + one space + abstract, with literal TSV quotes preserved.

Run the wrapper from the evidence-engine repository:

```bash
python scripts/score_official_drugprot.py \
  --predictions data/drugprot/rule_baseline/relations.tsv \
  --custom-metrics data/drugprot/rule_baseline/metrics.json \
  --output data/drugprot/official_rule_eval_v1
```

Use a **new** output directory for every evaluation. The wrapper rejects unexpected PMIDs, duplicate tuples, unknown relation types, incorrect CHEMICAL/GENE argument direction, wrong source hashes and modified evaluator source. It copies inputs into the new directory because upstream `filter_pred()` creates a temporary TSV next to the supplied predictions. Native abstracts, entities, gold relations, prediction files and upstream source are rehashed after execution. It never writes beside the original predictions.

The child process invokes the unchanged official `main()` pipeline. An observer first calls the original metric function, then calculates full-precision sklearn micro scores on the **same official arrays**. This captures values hidden by upstream rounding without repairing, replacing or changing array construction. Both original stdout and same-array measurements are retained. The strict custom scorer is separately recomputed from directed `(PMID, relation, chemical ID, gene ID)` tuples. Equality is checked numerically, rather than assumed from a displayed three-decimal score.

The upstream code was developed with Python 3.8 and pins pandas 1.2.4, numpy 1.20.2 and scikit-learn 0.24.2. No legacy environment was installed globally. Actual local execution succeeded with Python 3.12.14, pandas 3.0.6, numpy 2.5.3 and scikit-learn 1.9.1. The wrapper records exact environment versions and uses UTF-8 mode to read native text on Windows. This confirms the measured run's compatibility; it does not claim every upstream edge case behaves identically across environments.

The actual direct CLI rule result was `p_micro=0.559`, `r_micro=0.021`, `f1_micro=0.041`. The separate same-matrix wrapper run completed successfully in 146.4 seconds; all native inputs, copied inputs and official source remained unchanged. Full-precision results differ slightly:

| Scorer | TP | FP | FN | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|
| Official unchanged matrix pipeline | 80 | 63 | 3,678 | 0.5594405594405595 | 0.021287919105907396 | 0.041015124327095615 |
| Strict directed tuples including PMID | 80 | 63 | 3,681 | 0.5594405594405595 | 0.02127093858016485 | 0.04098360655737705 |

Thus the displayed three-decimal scores agree, but **exact parity is false**. Full outputs, environment, source/inputs/output SHA256 values and the discrepancy ledger are recorded in `drugprot_official_evaluator.json`.

Source inspection found a document-boundary indexing issue in upstream [`utils.format_relations`](https://github.com/tonifuc3m/drugprot-evaluation-library/blob/6b939554de38dbb69c462cc0d45c1cb17c3eaf57/src/utils.py): advancing by the final zero-based combination index reuses one matrix slot at each boundary. A two-document, one-combination-per-document reproducer makes a prediction from the wrong PMID count as a match in those arrays. Independent replay of the native entity order and original index rule identified exactly three INHIBITOR gold-slot collisions: PMID pairs 23506741/23511016, 23164921/23172777 and 17594192/17593236. The official matrix contains 3,758 gold positives rather than the native 3,761 distinct relations, explaining the actual FN and recall/F1 difference. The exact tuple IDs and slots are preserved in the JSON ledger. The official code remains unchanged; the official and strict tuple scores must be reported separately.

Seven local checks passed: native counts and exact metrics, duplicate rejection, unexpected PMID rejection, native hash mismatch rejection, pinned source/CLI output parsing, original-file immutability and the boundary-collision reproducer. These tests did not invoke or alter ongoing Qwen inference.

Qwen scoring remains pending until all 750 documents are present in its frozen merged run. Then run the same wrapper with the completed Qwen relations and custom metrics, using `data/drugprot/official_qwen_eval_v1` as a new output directory. Gold mentions are supplied to both models; this evaluates relation extraction on the development cohort. It does not measure NER, unseen pretraining contamination, food-domain precision, therapeutic benefit or binding affinity.
