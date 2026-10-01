The ongoing DrugProt inference remains frozen at batch 4, NF4/BF16, greedy
decoding, input 8,192 and output 1,024. The separate literature run prespecifies
batch 8 and retains every document in the response ledger, including explicit
empty abstentions for records without scoped chemical-gene co-mentions. Batch
timing, token counts and GPU allocated/reserved memory are recorded. No gold
metric determines batching.

The [official Qwen2.5-7B configuration](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct/raw/main/config.json)
has 28 layers, 4 key/value heads and head dimension 128. A conventional BF16
key/value cache therefore needs 2×28×4×128×2=57,344 bytes per token per document.
At a padded 9,216-token length, the cache alone is about 3.94 GiB for batch 8 and
7.88 GiB for batch 16. These are theoretical cache estimates; model weights,
activation/workspace memory and allocator overhead are additional. Batch 16 can
exceed a 16 GB card's available memory for long records. Actual batch 8 throughput
must be measured rather than inferred from these estimates.

The [Transformers optimization guide](https://huggingface.co/docs/transformers/main/en/llm_optims)
describes SDPA, static caches/compilation and continuous batching. This project
already uses SDPA. Compilation/cache changes and speculative decoding would
create a separate operational protocol and require hardware validation; they
are not introduced into the active frozen DrugProt run. No speedup is claimed
without an actual timing record.
