# Executed neural extension

The raw pretrained BiomedBERT revision `e1354b7a3a09615f6aba48dfad4b7a613eef7062` was fine-tuned anew. The relation-presence model uses native BioCreative VIII chemical/gene gold entities, development-only epoch/threshold selection and a once-unlocked final split. AUROC0.876 [0.851,0.898], lexical comparator0.666. This is not food efficacy or automatic end-to-end extraction. ChemProt previously exposed through DrugProt was excluded from independent final evaluation. Unobserved raw-pretraining overlap remains unknown.

BC2GM official sentence-held-out gene detection is separately documented in `../biomed_ner_20261003_v1`: precision0.816, recall0.851, F10.833. PMID-based article independence is unverifiable. Compound detection, PICO, negation/speculation scope and typed end-to-end extraction remain unvalidated; these metrics cannot be inherited from the binary relation model.

Training commands (use new immutable output directories):

```sh
python scripts/prepare_neural_corpora.py --help
python scripts/run_neural_relations.py --data SEALED_BIORED_BC8_V2 --out NEW_RELATION_OUTPUT --literature-source AUTHORIZED_PROTOTYPE_SOURCE
python scripts/run_biomed_ner.py --raw AUTHORIZED_BC2GM_IOB --out NEW_NER_OUTPUT --epochs 5
```

Acquire public corpora from the native source URLs and hashes recorded in the frozen protocols, audit exact PMID/text overlap and seal the split before learning. Do not reuse final labels for development. The original prototype is accessed read-only and is not reinstalled into the shared algorithm environment.

The actual safe5070 environment used torch2.11.0+cu128, transformers4.57.3, tokenizers0.22.2, numpy2.4.6, scikit-learn1.9.0, scipy1.17.1 and safetensors0.8.0. Relation fine-tuning used8epochs,384tokens,batch2/accumulation8; NER used5epochs. CUDA memory was explicitly bounded and unrelated GPU jobs were preserved. Exact model/output hashes are linked by the final-report acceptance bundle and individual receipts. No old scores or checkpoints were substituted.

Raw corpus text, original annotations, model weights and caches are local research inputs, not committed. The local NER prediction-with-word table is retained for audit but omitted from the Git snapshot; its hash and acquisition/reproduction instructions remain available.
