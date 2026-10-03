# Public expansion, 2026-10-03

The isolated staged DuckDB is `/home/keunsoo/projects/nutriomics-2026-final/expansion_20261003/derived/expansion.duckdb` on Z10PE. Its persistent views reference absolute Parquet paths in the same directory. Open it read-only. The lookup SQLite contains food and FFQ participant metadata. Neither writes to the active production graph.

`integration_receipt.json` contains executed SQL, metric units, exact baseline artifacts, source-versus-deduplicated counts, modality contexts and final hashes. `allrow_audit.json` records complete SQL checks and output/code hashes. Native archives and measurements stay outside Git. The serving database can only be called frozen when the final audit passes; copy its receipt and Parquets together.

Actual frozen audit: all30 SQL checks passed. DuckDB SHA256 is `91ac8845e1addd2b94191af48116ecd1cf6762c7343b6070a85229bd6207d033`; final summary SHA256 is `50ea86b1cf46f94dd9e2f199d08a9c522af807a61d51696e83395d9afe554b6c`; integration receipt SHA256 is `4111fb4dc0001f4b686810dc27f6bc94a6c4f964294f8842121f2d36f7528b02`.

| Registry | Native or pre-QC rows | Eligible or deduplicated rows | Unit |
|---|---:|---:|---|
| USDA food | 2,101,270 | 463,172 | Native source IDs versus GTIN/market or nonbranded food identities |
| Added USDA food | 2,095,475 | 457,377 | New native IDs versus new canonical IDs relative to frozen baseline |
| USDA serving composition | 7,189,227 | 7,186,264 | Unique nutrient records; 2,963 impossible mass values rejected |
| COCONUT | 738,794 | 724,254 | Full-key distinct source-InChI-verified single-component structures |
| BindingDB | 3,243,660 raw rows; 3,246,247 valid endpoint values | 3,171,536 | Source/assay/endpoint/condition/construct deduplicated measured assertions |
| Exact BindingDB labels | — | 2,551,272 | Exact positive measurements only |
| Kd/Ki BindingDB | — | 738,105 | Affinity assertions including censored values, separate from IC50/EC50 |
| CTD | 3,171,202 | 3,171,202 | Curated response records; 1,332,085 human records |
| Food standard analytes | 33 concepts | 33 | Standard chemical concepts with official positive food evidence; native exposure limitations retained |
| USDA isoflavone | 2,429 | 1,885 | Single-analyte measurements; total isoflavones excluded |

The 1M standardized-record, 90k added-food and 400k natural-structure thresholds pass with these stated units. The 1.68M threshold passes for measured all-endpoint assertions and also for 2,359,030 distinct construct-preserved compound–target pairs. It does not pass for Kd/Ki-only affinity assertions. The 2,000-food-compound threshold remains unmet. Thirty-three standard concepts are usable evidence; they do not establish 33 native free-ligand exposures.

## Counting and identity

- FDC native IDs include source versions and laboratory acquisitions. The serving `food` view includes only branded, SR, foundation and FNDDS food types. Branded identities use padded GTIN plus market and the latest publication; nonbranded records use native FDC ID. Names alone never merge food identities. The exact frozen baseline has 6,321 food nodes: 5,795 FDC, 50 K-FIND and 476 USDA-flavonoid nodes. Earlier 5,845 is a stale reported baseline, not the current snapshot denominator.
- `food_composition` preserves nutrient units and `source100g` basis. Nonfinite/negative values and missing nutrient definitions are excluded. Mass exceeding 100g, 100,000mg or 100,000,000ug per100g is physically impossible and remains in `food_composition_rejections`. Activity/IU values are not converted into mass. Overlapping nutrients are not summed. Manufacturer labels and source analytical values remain different evidence.
- COCONUT source standard InChI generates the identical full InChIKey, including stereochemistry. Disconnected structures are excluded from the distinct single-structure count. This verifies the source InChI hash, not every SMILES independently. FooDB collection membership and LOTUS whole-organism occurrence do not establish an edible part or a measured food occurrence. They are never promoted into 2,000 verified food compounds.
- CTD chemical–gene records are curated molecular responses, not measured ligand binding. The complete native columns and PMID lists remain in the dedup hash.
- BindingDB preserves Ki, Kd, IC50 and EC50 as separate native nM endpoints, plus exact/censored/approximate relations. The broad registry is distinct from the strict Kd model. A source InChI must reproduce the full InChIKey and all declared protein chains remain represented. Native target names/species/constructs and assay/source conditions remain in measurement identity. DOI/PMID/patent aliases are conservatively joined; possible unrecognized cross-source replicates remain a limitation. All endpoints are measured activity assertions; IC50/EC50 are not automatically physical binding affinities. Untested pairs never become negatives.

## Four actual data types

| Type | Actual query layer | Participant interpretation |
|---|---|---|
| Individual genotypes | `genotype_reference_call`, `genotype_reference_sample` | IGSR phase3, GRCh37 chr11:61560000–61750000; 2,504 reference individuals; no dietary cohort matching |
| Epigenomics | `methylation_abundance`, `methylation_sample` | GSE193795 132 + GSE42774 16; existing source-processed beta matrix; no new raw IDAT reprocessing |
| FFQ | `ffq_frequency`, `ffq_participant` | NHANES 2003–2006 actual FFQ; cycle+SEQN; `has_ffq_frequency` separates respondents from all demographics |
| Metabolomics | `metabolomic_abundance`, `metabolomic_sample` | ST001257: 19 humans, 76 urine and 14 food preparations; 11,693 anonymous analytical features, not identified compounds |

These cohorts contain different people. Their cells, participants and studies cannot be added as a single clinical cohort. FFQ retains its dedicated `WTS_FFQ`, other survey weights, strata and PSU; frequencies have no portion size and do not estimate absolute nutrient intake. Observed single-visit blood pressure averages and self-reported diagnosis are separate labels. No survey-adjusted clinical inference was performed.

## Reproduction

Use Python3.12 with duckdb, pyarrow, pandas, numpy, rdkit, requests and pysam. The CPU frozen versions are in the integration receipt. Use at most two ETL threads. Raw source receipts require full archive integrity and SHA validation before loading.

Exact executed code SHAs are in `code_provenance.json`. The executed acquisition source is preserved in `executed_code/acquire_public_expansion.py`; the current package acquirer only removes unreachable code and closes its XPT header file handle. Scientific ETL scripts match the remote frozen SHAs. The CLI wrapper and transport helper were not remote scientific transformations.

```bash
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2
TASK=/home/keunsoo/projects/nutriomics-2026-final/expansion_20261003
PY=/home/keunsoo/projects/nutriomics-2026-final/.venv/bin/python
# Installed evidence-engine package, or set PYTHONPATH to its src directory.
$PY scripts/acquire_public_expansion.py --root "$TASK"
$PY scripts/acquire_reference_genotypes.py --root "$TASK"
$PY scripts/stage_public_expansion.py --root "$TASK" --threads 2 --baseline "$TASK/baseline_food_snapshot.sqlite"
$PY scripts/register_public_modalities.py --root "$TASK" \
  --methyl-prepared /home/keunsoo/projects/nutriomics-2026-final/nutriomics-htn-methylation/data/prepared \
  --metabolomics-source "$TASK/raw/ST001257" \
  --atlas-src /home/keunsoo/projects/nutriomics-2026-final/nutriomics-intervention-atlas/src
$PY scripts/stage_bindingdb_endpoints.py --root "$TASK"
# Optional frozen DTI USDA/PubChem panel: copy its exact manifest inputs first.
$PY scripts/register_food_analyte_panel.py --root "$TASK"
$PY scripts/audit_public_expansion.py --root "$TASK"
$PY scripts/public_expansion_receipt.py --root "$TASK"
```

`correct_food_mass_units.py` migrates the first staged composition version explicitly, retaining the pre-correction artifact/hash. The current base ETL already implements the mass guard, so this migration is not required on a fresh rebuild. Its four-analyte CSV uses single caffeine, theobromine, D2 and D3 concepts; combined D2/D3 quantities are excluded from structural mapping.

Small fixture verification: `python -m pytest tests/test_public_expansion.py tests/test_bindingdb_endpoints.py -q`. Tests cover native archive hash corruption, GTIN dedup, laboratory exclusion, exact baseline deltas, mass limits, FFQ survey design and label distinctions, full-key/mixture checks, censoring, source-assay dedup and invalid-structure quarantine.

## Source access and rights

Primary sources: [USDA FDC April2026](https://fdc.nal.usda.gov/download-datasets/), [COCONUT October2026](https://coconut.naturalproducts.net/download), [LOTUS frozen January2023](https://zenodo.org/records/7534071), [CDC FFQ methodology](https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2003/DataFiles/FFQDC_C.htm), [IGSR official phase3 release](https://ftp.1000genomes.ebi.ac.uk/vol1/ftp/release/20130502/), [BindingDB](https://www.bindingdb.org/rwd/bind/chemsearch/marvin/Download.jsp), [GEO](https://www.ncbi.nlm.nih.gov/geo/), [ST001257](https://www.metabolomicsworkbench.org/data/DRCCMetadata.php?Mode=Study&StudyID=ST001257).

Source-level URL/version/license notes and SHA are in each acquisition receipt and the `source_registry` view. US federal data, COCONUT CC0 and LOTUS CC0 remain separately recorded. Research access does not imply raw redistribution rights. FooDB official bulk requests returned403; September2026 BindingDB returned404. No failed acquisition, historical independence or 2,000-food-compound milestone is reported as complete.
