# Nutriomics evidence engine

Private source-backed research implementation for the 2026 NutriGenomics final report. It builds a hypertension evidence graph from actual CTD snapshots and verified food composition records. It also provides a conservative DrugProt rule baseline and a strict parser for generated evidence JSON. A successful model-output parse establishes entity and quotation validity; scientific entailment still requires review.

## Install and tests

Python 3.11+; runtime dependencies are DuckDB and PyArrow. RDA XLSX input additionally requires `openpyxl`. Model inference is a separate process.

```sh
python -m pip install -e '.[dev]'
mkdir -p artifacts
python -m pytest -q --basetemp artifacts/pytest_tmp
```

If pip cannot access its build dependencies, use an existing environment with setuptools and `pip install --no-build-isolation -e .`. Alternatively run `PYTHONPATH=src python -m nutriomics_evidence ...`; in PowerShell set `$env:PYTHONPATH = (Join-Path $PWD src)`.

## CTD ingestion and graph

```sh
nutriomics-evidence ingest-ctd --source-dir /path/to/CTD \
  --output-dir artifacts/ctd-2026-09-29 --source-registry artifacts/source-registry.json
nutriomics-evidence build-graph --input-dir artifacts/ctd-2026-09-29 \
  --database artifacts/hypertension.sqlite
nutriomics-evidence validate --database artifacts/hypertension.sqlite
nutriomics-evidence query --database artifacts/hypertension.sqlite \
  --disease MESH:D006973 --tier curated --limit 10
```

Default ingestion reads seven files: chemical–gene interactions, both curated disease files, chemical and disease dictionaries, gene–pathway annotations and pathway dictionary. Standard CSV quoting, schema-width checks and gzip CRC/footer are verified through EOF. SHA-256 identifies original bytes and Parquet outputs. Header dates identify releases; filesystem times do not. `.crdownload` files are rejected. Changed source bytes require a new output directory. Unchanged ingestion verifies artifacts and rebuilds DuckDB views after relocation.

To include protein cross-references, additionally ingest `CTD_genes.csv.gz`. To include inferred chemical–disease evidence, additionally ingest `CTD_chemicals_diseases.csv.gz` and build with `--include-inferred`:

```sh
nutriomics-evidence ingest-ctd --source-dir /path/to/CTD \
  --output-dir artifacts/ctd-2026-09-29 \
  --files CTD_genes.csv.gz CTD_chemicals_diseases.csv.gz
nutriomics-evidence build-graph --input-dir artifacts/ctd-2026-09-29 \
  --database artifacts/hypertension.sqlite --include-inferred --overwrite
```

Graph scope is exact `MESH:D006973` (Hypertension) and `MESH:D000075222` (Hypertension, Essential). Chemical–gene rows require `OrganismID=9606` and both endpoints in the selected curated disease sets. Disease exports do not encode species; this limitation is retained. Human experimental interactions do not imply clinical trials. Dictionary hierarchy roots such as `MESH:D` are kept in bulk data but never promoted to molecular nodes.

`marker/mechanism`, `therapeutic` and inferred evidence remain distinct. Curated/full export overlap has one edge with multiple source links; PMID citations merge without duplicate counting. Distinct interaction text, action sets and gene forms remain distinct contexts. Inference scores are source scores, not probabilities. CTD `affects^binding` is not a direct ligand-binding or DTI training label. The engine does not infer causal food-to-health effects.

SQLite tables: `source`, `node`, `edge`, `edge_source`, `citation`, `identifier_mapping`, `measurement`. Coverage reports contain relation counts and unresolved structures. Queries return source IDs, PMIDs and context together. `export --output evidence.json` marks `redistribution_verified=false`; source-specific reuse conditions still apply. Raw snapshots and large artifacts are ignored by Git.

## Food composition and identity

```sh
nutriomics-evidence ingest-food --format fdc --input /path/food.json /path/FoundationFoods.zip \
  --database artifacts/hypertension.sqlite --source-registry artifacts/source-registry.json
nutriomics-evidence ingest-food --format kfind \
  --input /path/raw-material-standard-2026-09-30 /path/food-standard-2026-09-30 \
  --selection config/kfind_food_selection.json --database artifacts/hypertension.sqlite
nutriomics-evidence ingest-identities --format pubchem --input /path/pug-properties.json \
  --database artifacts/hypertension.sqlite
```

FDC admits SR Legacy, Foundation and Survey/FNDDS detail JSON and official JSON ZIP wrappers. Branded serving-only records are rejected. Source nutrient derivations are retained: calculated/derived and imputed-zero values differ from measured values. `meal` includes only measured classes. Each food has one explicitly ingested active source release, avoiding double summation of older releases. FoodOn annotations describe food concepts; they do not establish molecular equivalence.

K-FIND ingestion verifies page/column hashes, page counts and total row counts. The selection contains 50 Korean foods inherited only as a reviewed input list from the earlier project's selection JSON; measurements are read again from raw releases. Exact dataset/code/name must uniquely match with analyzed values and verified 100 g basis. Preparation and `REFUSE` are retained; cooking/edible-portion conversions are not guessed. Missing, below-detection and measured-zero values remain distinct.

RDA CSV/XLSX requires explicit mapping JSON: `source_url`, `version`, `basis="source_100g"`, `basis_verified=true`, `food_code`, `food_name`, and `nutrients` (source column to `id`, `name`, `unit`). XLSX additionally requires `sheet` and optional `header_row`; CSV supports `encoding`. The adapter does not establish that an RDA source has actually been acquired or run.

CTD CID/InChIKey/DTXSID and optional UniProt cross-references are `source_reported`. Reviewed identity JSON contains `source_url`, `version`, `mappings`; each mapping requires `subject`, `namespace`, `identifier`, `relation`, `basis`. `exact_structure` additionally requires identical valid full standard InChIKeys, `method="same_standard_inchikey"`, `reviewed=true`, no mixture, and independently loaded source properties for both nodes. Names remain `candidate_name`. FDA UNII alone is regulatory identity. A gene symbol never supplies a fabricated protein sequence.

`meal --input meal.json` accepts `{"foods":[{"food_id":"FDC:171688","grams":150}]}` and reports composition sums plus excluded/unknown quantities. It does not predict blood concentration or clinical response.

## Literature extraction and evaluation

```sh
nutriomics-evidence extract-drugprot --abstracts /path/development_abstracs.tsv \
  --entities /path/development_entities.tsv --output artifacts/rule-relations.tsv \
  --evidence-output artifacts/rule-evidence.json --prompt-output artifacts/qwen-prompts.jsonl
nutriomics-evidence evaluate-drugprot --abstracts /path/development_abstracs.tsv \
  --entities /path/development_entities.tsv --gold /path/development_relations.tsv \
  --predictions artifacts/rule-relations.tsv --output artifacts/rule-evaluation.json
```

DrugProt character offsets are checked against `title + " " + abstract`. The baseline accepts one chemical/gene pair in one non-negated sentence with an explicit cue. It uses the 13 official relation classes and benchmark gold entity mentions: this evaluates relation extraction, not end-to-end NER. Exact tuple micro/per-class precision, recall and F1 report real counts; the official evaluator is the challenge reference: [DrugProt corpus and scripts](https://github.com/tonifuc3m/drugprot).

Model responses are JSONL records `{"pmid":"...","response":{...}}`. Use `parse-qwen --documents artifacts/rule-evidence.json --responses responses.jsonl --output artifacts/qwen-validation.json --relations-output artifacts/qwen-relations.tsv`. Allowed relations, known chemical/gene IDs, argument direction, exact quotation and offsets covering both mentions are required. Unknown keys, invented affinities, bad offsets and unknown relations are rejected. Quoted negation is sent to review. Missing documents are reported. Accepted rows retain `semantic_entailment_validated=false`; parser acceptance is not scientific validation or proof that Qwen inference was run.

## Verification status

### Existing literature summary prototype

The user's **LLM 문헌요약 시스템 계획** prototype is reused through its immutable report interface. Exact source copies and the independent pinned environment are in `integrations/literature_service`; provenance is in `docs/literature_service_source_manifest.json`. This is a `heuristic-v1` CPU summary/reviewer service, separate from Qwen relation inference. The frozen report contains597 unique PMIDs,325 licensed XML full texts,597 current summaries,1,465 automatic candidates and0 human-approved relations. Expert annotation and scientific precision/recall are pending. Operating software tests are not scientific accuracy scores.

```sh
python scripts/import_literature_service.py \
  --report /path/to/literature_service/runtime/reports/02410eff582343e59818008de87b77e9/snapshot.json \
  --expected-sha256 023fe5e1e187dd31049f508344697da0db470735388acbe6de4605348a5785a2 \
  --database artifacts/literature_snapshot_v3.sqlite \
  --previous-manifest docs/pubmed_source_manifest.json \
  --deployment /path/to/literature_service/runtime/validation/deployment.json \
  --receipt docs/literature_service_integration.json
```

This writes a separate immutable SQLite view. It never modifies the live service DB or CTD graph and never promotes automatic relations to curated binding/clinical labels. Provider exact-span checks are recorded as provider receipts, not independently repeated semantic validation. PMID overlap with the original1,198 selected documents is91; the union is1,704. Heterogeneous publication dates, including updated book chapters, are preserved rather than silently forced to the service's query-start year. The final-report API exposes summaries and source-aware candidate filters under `/literature/`. Source quotations and the snapshot database remain outside Git, including private Git.

See `docs/validated_snapshot.json` for completed source validation and measured coverage. Test fixtures validate implementation and are never model performance evidence. Existing `NutriOmics_DB_c` import code was inspected as a reference; its Django/dev-corpus machinery was not used to establish this new snapshot's evidence.

Audit every completed local CTD file without producing additional Parquet tables with `audit-ctd --source-dir /path/CTD --previous-manifest artifacts/ctd-2026-09-29/manifest.json --output artifacts/ctd-all-files-audit.json --workers 4`. A prior complete ingestion is reused only after verifying the original source hash. Other files are fully streamed; failures are recorded and return a nonzero exit status. No partial download is opened.

Generate a reviewable run summary after execution:

```sh
python -m pytest -q --basetemp artifacts/pytest_tmp --junitxml artifacts/test-results.xml
python scripts/record_validation.py --manifest artifacts/ctd-2026-09-29/manifest.json \
  --database artifacts/hypertension.sqlite --ctd-audit artifacts/ctd-all-files-audit.json \
  --junit artifacts/test-results.xml --output docs/validated_snapshot.json
```

The summary derives test counts from JUnit and graph counts from SQLite. Optional `--drugprot-evaluation` records a completed real corpus evaluation; without it, corpus/model evaluation is explicitly unrecorded.
