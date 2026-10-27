**English** | [한국어](README.ko.md)

# NutriOmics Evidence Engine

This repository connects food composition, chemical-gene-disease relationships and literature sources in a searchable evidence database. It processes CTD records for hypertension research and stores food composition and FDA conditions of use as separate evidence types.

[Database results and input hashes](docs/validated_snapshot.json) | [Literature extraction results](docs/qwen_drugprot_summary.json) | [NutriOmics web platform](https://github.com/kangk1204/nutriomics-db) | [Project report, restricted access](https://github.com/kangk1204/nutriomics-final-report)

## What the software does

- Checks compressed CTD files and column layouts, then writes normalized Parquet files.
- Links foods, compounds, genes, diseases and pathways through identifiers.
- Preserves PMID references, source records, species, tissues, experimental conditions and evidence types for each relationship.
- Distinguishes measured values, calculated values, zeros and missing food composition values.
- Queries the SQLite evidence database by disease and evidence type.

The initial disease scope covers hypertension (`MESH:D006973`) and essential hypertension (`MESH:D000075222`). Human chemical-gene relationships use taxonomy ID `9606`.

## Initial database results

The CTD source files were released on September 29, 2026. The table below describes the initial hypertension evidence database checked on October 1, 2026.

| Item | Count | Counting unit |
|---|---:|---|
| CTD chemical-gene source data | 3,171,202 | Rows in the complete source files |
| CTD direct chemical-disease source data | 109,737 | Rows in the complete source files |
| CTD direct gene-disease source data | 34,315 | Rows in the complete source files |
| Evidence database nodes | 8,120 | Identified entities, including foods, compounds, genes, diseases and pathways |
| Evidence database relationships | 426,922 | Food composition, literature and pathway relationships |
| Citation records | 66,833 | References attached to database evidence |
| Food composition records | 369,408 | Food-component records with measurement, calculation or missing-value status |

The relationship count includes food composition links. Complete CTD source counts, the hypertension subset and [subsequent integrated database counts](https://github.com/kangk1204/nutriomics-final-report) are reported separately. The integrated report repository requires access permission.

## Reading the evidence

| Evidence type | Information provided |
|---|---|
| Food composition | Component amounts, units and measurement status from each source |
| Direct literature evidence | Chemical, gene and disease relationships curated by CTD from publications |
| Inferred relationships | Associations derived by linking direct evidence |
| Model predictions | Candidate literature relationships and prediction scores |
| FDA conditions of use | Ingredient specifications, intended uses and conditions of use |

CTD chemical-gene relationships include molecular responses such as changes in gene expression. Binding-affinity prediction from measured Kd values is available in [DearDTI KFRI](https://github.com/kangk1204/DearDTI_kfri). Confirmed chemical matches use structure identifiers; name-based candidate matches retain their review status.

## Literature analysis and the web platform

This repository contains the initial comparison of rule-based extraction with Qwen2.5-7B-Instruct, together with the literature service integration code. On the 750-document DrugProt development set, strict relation-extraction F1 was **0.041** for the rule-based method and **0.000** for Qwen. The denominator included all documents: 726 generated responses and 24 memory failures.

Subsequent BiomedBERT relation classification, entity recognition, literature search and summary interfaces are described in the [NutriOmics literature platform](https://github.com/kangk1204/nutriomics-db#문헌-분석-결과). Evaluation with supplied reference entities and evaluation of fully automatic extraction are documented separately.

| Information | File |
|---|---|
| CTD and food database validation | [validated_snapshot.json](docs/validated_snapshot.json) |
| Rule-based and Qwen extraction results | [qwen_drugprot_summary.json](docs/qwen_drugprot_summary.json) |
| Official DrugProt evaluator results | [drugprot_official_qwen_evaluator.json](docs/drugprot_official_qwen_evaluator.json) |
| Literature service integration | [literature_service_integration.json](docs/literature_service_integration.json) |
| Reused source files | [literature_service_source_manifest.json](docs/literature_service_source_manifest.json) |

## Installation and use

Use Python 3.11 or later.

```sh
python -m pip install -e ".[dev]"
nutriomics-evidence --help
python -m pytest -q
```

After obtaining the CTD files, run:

```sh
nutriomics-evidence ingest-ctd --source-dir /absolute/path/to/CTD --output-dir artifacts/ctd --source-registry artifacts/source-registry.json
nutriomics-evidence build-graph --input-dir artifacts/ctd --database artifacts/hypertension.sqlite
nutriomics-evidence validate --database artifacts/hypertension.sqlite
nutriomics-evidence query --database artifacts/hypertension.sqlite --disease MESH:D006973 --tier curated --limit 10
```

Parquet stores normalized source records, and SQLite supports evidence queries. Source datasets and generated databases are held in research data storage. This repository provides code, schemas, counts and file hashes.

## Sources and licensing

CTD, food composition and FDA data are collected and analyzed under their providers' terms. Source identifiers and hashes are recorded in the [database results](docs/validated_snapshot.json). Literature full text is stored according to each publication's access and reuse terms.

The code is available under the [MIT License](LICENSE). [Software and data licenses](DATA_LICENSES.md) lists the sources and terms for external data and models.
