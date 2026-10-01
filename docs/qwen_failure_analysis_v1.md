# Frozen Qwen failure analysis

The full750 strict result remains unchanged: TP0, FP5, FN3761, F1=0. Numeric offset validity is distinct from textual or semantic relation support.

- Invalid source spans: 1676 relation rows. Exact-quote occurrence categories: `{'unique_exact_occurrence': 1430, 'multiple_exact_occurrences': 134, 'no_exact_occurrence': 112}`.
- Invalid-span rows with a unique exact quotation containing both correctly typed native argument spans: 164.
- Original JSON/top-schema failures: 156 documents; includes24 empty generation-error responses. Counts overlap and must not be added.
- Generation errors:24 documents in three batch8 CUDA out-of-memory groups. No model output exists for these documents; they remain abstentions.
- Generated responses reaching the output limit: 12.

All measurements come from frozen raw responses and native source mentions, without opening reference relations in the diagnostic stage. Numeric and text grounding failures do not prove semantic accuracy. No JSON suffix, quotation, whitespace, ID or label repair is used. Raw quotations remain in ignored local data; this report publishes only counters and hashes.
