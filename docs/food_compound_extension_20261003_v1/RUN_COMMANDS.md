# Execution and strict completion

Run on the authorized Z10PE CPU host. The existing broader snapshot is frozen. Continue only its separate strict audit:

```bash
ROOT=/home/keunsoo/projects/nutriomics-2026-final/expansion_20261003/food_compound_extension_v1
PY=/home/keunsoo/projects/nutriomics-2026-final/.venv/bin/python
$PY "$ROOT/strict_v2_code/food_compound_extension.py" --root "$ROOT" --phase strict-audit-v2
```

The CLI file is `scripts/food_compound_extension.py`. Its module is `src/nutriomics_evidence/food_compound_extension.py`; a standalone server deployment copies it next to the CLI as `food_compound_extension_module.py`. Version2 was deployed and executed in `strict_v2_code`. Keep the executed `code`, `final_code` and `strict_code` snapshots unchanged for provenance. The read-only version2 step writes only `derived/strict_v2`, preserving the broader DB and all prior frozen data. It has completed; independent reproduction must use a new directory rather than overwrite the frozen version2 receipts.

Independent reproduction must use a new directory, never the frozen snapshot. Place the current code in that new directory's `code` and `final_code` folders, then execute:

```bash
ROOT=/home/keunsoo/projects/nutriomics-2026-final/expansion_20261003/food_compound_extension_v1_rebuild
PY=/home/keunsoo/projects/nutriomics-2026-final/.venv/bin/python
$PY "$ROOT/code/food_compound_extension.py" --root "$ROOT" --phase acquire
$PY "$ROOT/code/food_compound_extension.py" --root "$ROOT" --phase stage
$PY "$ROOT/final_code/food_compound_extension.py" --root "$ROOT" --phase finalize
```

The native archives and derived records remain outside Git. No GPU is required. The directory must remain one level below `expansion_20261003` so the previous frozen expansion guard resolves correctly.

The first staging attempt was terminated by its owner after reproducing an unintended DuckDB nested-loop plan. The equivalent namespace-preserving `CASE` join key generates a hash join and passed the same regression guard. The corrected complete ETL and subsequent read-only finalization succeeded. Structure verification and food occurrence eligibility were unchanged.

Frozen broader DB SHA256: `5c32800b4906c0614e5fc51df44bf9cbef54f12dd24c45318f055dc41313d5e8`. It stores 4,630 standardized structure concepts, 345,624 eligible occurrence records and 822 food IDs. Positive records cover 2,563 keys; qualitative-only records cover 2,067. These broader concepts do not automatically satisfy the strict verified single-analyte target. The immutable previous expansion SHA256 still matches `91ac8845e1addd2b94191af48116ecd1cf6762c7343b6070a85229bd6207d033`.

Completed positive-only overlap query found 1,402 milk-assigned keys and 1,294 keys with nonmilk evidence, including 133 shared keys. All sampled milk Content records lacked an original measured analyteID/name. The strict audit excludes those unresolved assignments unless a future separate source mapping is established; it also removes generic classes, elemental totals and unspecified standard stereochemistry. It examines quantitative and qualitative records separately. Qualitative presence requires a specific source publication and does not require an amount.

The strict audit completed after Z10PE SSH recovered. Version2 corrected a generic Vitamin D total that cannot resolve D2/D3 identity: 263 unique positive single-analyte structures and 12,920 source records across 633 food IDs; zero qualitative records passed its identity/reference guards. All six strict checks passed. The 2,000 target remains unmet. Exact-name and standard-stereo guards can conservatively exclude true synonym-linked compounds; rejected record counts do not establish chemical absence. Use `acceptance_receipt.json` for final target evaluation, with its strict count SQL and output hashes. The broader receipt's coverage flag concerns standardized representations and must not replace the strict target unit. Earlier strict264 files are preserved as historical version1 evidence.

Z10PE SSH temporarily disconnected after the broader finalization, interrupting receipt transfer and inspection. No own computational job remained running at that disconnection. The connection recovered, the strict audit ran, and all compact receipts transferred. No unrelated service was stopped or restarted.

Local focused checks:

```powershell
& C:/Projects/00_NutriGenomics_auto/final_2026/.venv/Scripts/python.exe -m pytest tests/test_food_compound_extension.py -q -p no:cacheprovider
```

Four tests pass. They cover exact structure recomputation and disconnected/aggregate rejection, food-specific edible-part pairs, an actual staged miniature dataset rejecting predicted/wrong-part/impossible records, and strict quantitative versus source-reported qualitative identity guards.
