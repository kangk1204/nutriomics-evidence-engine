# Food compound extension: current strict acceptance

The additional author-provided FooDB source is acquired, staged and audited on Z10PE. Current acceptance is **263 source-named single analytes**, **12,920 positive occurrence records**, and **633 native food IDs**. The 2,000-compound target is **unmet**. No amount-free qualitative record passed the strict original-identity and specific-reference guards. Four focused tests pass; all 18 broad and six strict complete-row checks return zero violations.

Use `acceptance_receipt.json` with `strict_receipt_v2.json`. It contains the count SQL, source-license links and source hashes, strict output hashes, frozen DB hash, audit results and limitations. `ERRATUM.md` explains the superseded broad true flag and the corrected generic Vitamin D assignment. `extension_receipt.json`, `strict_receipt.json` and `acceptance_receipt_superseded_v1.json` are historical receipts and must not supply final target acceptance.

| Source/audit layer | Actual count | Interpretation |
|---|---:|---|
| Source Compound records | 70,477 | Native historical snapshot rows |
| Dual-verified single structure rows | 68,436 | SMILES and InChI both reproduce the source full key |
| Source Content records | 5,145,532 | Compound and Nutrient namespaces preserved |
| Broader eligible food occurrence records | 345,624 | Numeric and curated/published qualitative tiers |
| Broader standardized structure concepts | 4,630 | Retained for exploration with native-form uncertainty |
| Strict quantitative analytes | 263 | Exact original source analyteID/name and structure gates |
| Strict quantitative occurrence rows | 12,920 | Source records; not new independent experiments |
| Strict qualifying qualitative analytes | 0 | Amount absent was permitted; identity/reference gates failed |
| Strict native foods | 633 | Distinct source food IDs, not added FDC food identities |
| Predicted HMDB/PathBank records excluded | 3,273,562 | Never treated as observed food occurrence |

The frozen broader DuckDB is `/home/keunsoo/projects/nutriomics-2026-final/expansion_20261003/food_compound_extension_v1/derived/food_compound_extension.duckdb`, SHA256 `5c32800b4906c0614e5fc51df44bf9cbef54f12dd24c45318f055dc41313d5e8`. Strict source records and standards are separate Parquets in `derived/strict_v2`; the DB was opened read-only during both strict audits. The full occurrence audit contains `strict_status`; filter accepted statuses to query all 12,920 records. The standards file contains one representative row per key and must not be used to reconstruct every food occurrence.

The previous frozen expansion and evaluated 33-standard DTI panel remain unchanged. Food occurrence does not establish native free-ligand exposure, a dose, healthy-effect accuracy or independent DTI validation. Exact-name guards conservatively exclude unresolved synonyms; rejected records do not prove absence. Milk species assignments are excluded because the measured-analyte-to-specific-structure mapping was unavailable.

`SOURCE_AUDIT.md` verifies the original study/repository relationship and separates upstream CC-BY-NC-4.0 data terms from MIT code. Native raw/derived data remain outside Git. `RUN_COMMANDS.md` gives isolated rerun commands and `environment.json` records the actual runtime. The `executed_stage_code` directory matches the code hashes in the transferred stage receipt.
