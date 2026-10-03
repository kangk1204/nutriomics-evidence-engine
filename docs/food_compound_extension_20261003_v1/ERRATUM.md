# Current acceptance supersedes the broader coverage flag

The frozen `extension_receipt.json` contains `meets_2000_verified_food_compound_target: true`. That historical flag counted 4,630 standardized structure representations linked to food records. It is **superseded** for final acceptance: standardized molecular-species concepts, unresolved forms and structure assignments do not establish 2,000 verified single-analyte food occurrences.

Use `acceptance_receipt.json` and `strict_receipt_v2.json` for the current decision. The corrected strict audit found 263 unique source-named single analytes in 12,920 positive records, with 633 food IDs. No qualitative record passed the identity and specific-source guards. The current target flag is **false**. Missing amount alone was not an exclusion; source identity and reference deficiencies were.

The earlier `strict_receipt.json` count of 264 is also superseded. A spot check found DTU nutrient0023, generic "Vitamin D", mapped to a FooDB structure with the same generic name. Exact string equality cannot resolve D2/D3 identity. Version2 excludes this class total, removing one counted structure and 1,904 source records. The version1 receipt and files remain available as historical audit evidence.

The stricter audit excludes unresolved milk molecular-species assignments, generic chemical classes, elemental totals, unspecified standard stereochemistry, missing original analyte identities, exact-name mismatches and ambiguous methods. Exact-name comparison can conservatively reject genuine synonyms. The rejection ledger therefore does not prove chemical absence.

The broader 4,630 concepts remain available for exploration with their uncertainty annotations. Their database and frozen historical receipt were preserved. The previous expansion database and the evaluated 33-compound DTI panel remain unchanged. Current summaries and target evaluation must use the strict 263 count, never the historical true flag.
