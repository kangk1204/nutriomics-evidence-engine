The DrugProt run started with batch 4 and a frozen 750-document development
cohort. Before inspecting Qwen relation scores, the coordinator authorized an
operational change to batch 8 for the remaining source documents. The original
responses and `inference_lock.json` remain read-only. The existing
`scripts/run_qwen.py` is unchanged.

`run_qwen_continuation.py` requires the same immutable official model, verified
model-file hashes, source abstracts/entities/gold hashes and reconstructed
prompt hash. It retains NF4 double quantization, BF16 computation, SDPA, greedy
decoding, input limit 8,192, output limit 1,024 and seed 42 once per process
start. Batches do not reseed. No finetuning, prompt edits, output repair or
score-based selection is introduced. The independently measured rule baseline
is not used to select this batching amendment. Different batch shapes or process restart
can change floating-point calculations and generated text; output parity is
not promised.

Stop the original process only after a flushed complete batch. The checkpoint
must contain a batch-4 prefix of the official source-document order. Each
original lock/response hash is frozen again in a new immutable continuation
lock, checked before every new batch and after final evaluation. Pending
documents retain source order and use batch 8. Each generated response,
context-overflow abstention and generation-error abstention stays in the cohort.
OOM retains an error abstention, with no automatic batching change or silent
document removal. A resumed continuation requires complete flushed batch-8
prefix records and identical locks/code/settings.

The pinned model configuration supplies the memory calculation. At 28 layers,
4 key/value heads, head dimension 128 and BF16 caches, a batch of eight padded
to 9,216 total tokens has about 3.94 GiB of key/value cache. This is a lower
bound on total inference allocation. The preflight also budgets 6 GiB for
parameters and 1.5 GiB for workspace before loading, then measures actual free
memory after loading and reserves cache plus workspace. These assumptions do
not guarantee every activation/prefill peak fits a 16 GB card. Actual memory,
per-batch token counts, elapsed time, seed policy and document IDs are logged.

Residual responses live in a separate directory. Only after the union contains
exactly all 750 expected PMIDs, with no duplicates, overlaps, missing or extra
records, are the original and residual responses scored together by the
unchanged parser/scorer. The final summary reports both execution protocols,
batch sizes, document counts, script/lock/response hashes and the operational
amendment. Scores describe this mixed execution of the public development
cohort with gold mentions; they do not establish NER, food-domain precision or
independence from model pretraining.

Example, reusing the original source/model arguments:

```text
python scripts/run_qwen_continuation.py --original-out <original-output>
  --model-dir <existing-model> --model-lock <existing-model-lock>
  --abstracts <same-abstracts> --entities <same-entities> --gold <same-gold>
  --out data/drugprot_qwen_continuation_v1
```
