This is a fresh **gene mention** classifier initialized from the pinned BiomedBERT backbone `microsoft/BiomedNLP-BiomedBERT-base-uncased-abstract-fulltext`, revision `e1354b7a3a09615f6aba48dfad4b7a613eef7062`. Its classification head is trained from scratch on the native BC2GM sentence split. This component does not classify compound–gene relations, estimate dietary efficacy or supply an AUROC for ingredient recommendation.

The frozen run uses seed 20261003, five epochs, AdamW at 2e-5, batch 4 with four-batch gradient accumulation, CUDA bfloat16 autocast, two CPU threads and a 0.36 GPU-memory fraction cap. The last incomplete accumulation window is correctly scaled by its actual microbatch count. Development exact-span F1 selects one checkpoint; final native test tags are interpreted only after that checkpoint's once-only predictions have been written and hashed.

The supplied splits contain 12,574 training, 2,519 development and 5,038 test sentences. Lowercase, space-joined native tokens identify 12 train/dev, 34 train/test and 15 dev/test unique-text intersections. Excluding overlapping upstream rows leaves 12,488 training and 2,494 development sentences. The native test split remains intact, including 23 repeated sentence rows; it has 5,015 unique normalized texts. The protocol records the exact source hashes. Text duplicate filtering does not establish independence between papers or pretraining corpora because this IOB distribution lacks PMID mapping.

Evaluation uses exact native-word span boundaries and entity type. An orphan `I-GENE` begins a span; an incorrect boundary counts as both a false positive and a false negative. Precision, recall, F1 and TP/FP/FN are saved even if the desired performance is missed. Tokens beyond the 254-wordpiece budget are split at complete word boundaries. All native words must appear exactly once, and first-wordpiece outputs are reconstructed across the complete sentence before span scoring. Padding, ignored continuation subwords, discarded words, duplicated coverage and truncated predictions are checked explicitly.

`neural_ner.NeuralGeneMentionProvider` provides a separate inference adapter for exact offsets in new source text. Offsets are Unicode codepoints, and each returned mention is checked against the original substring. Gene identifiers are not inferred by this adapter. The automatic source-tokenization path has unit tests, but it is separate from native BC2GM word-span evaluation and must not inherit an unmeasured end-to-end literature accuracy claim.

Reproduce the training command from the workspace root on an authorized GPU:

```text
python final_2026/repos/nutriomics-evidence-engine/scripts/run_biomed_ner.py --raw final_2026/expansion_20261003/nlp/raw --out final_2026/expansion_20261003/nlp/ner_v1 --epochs 5
```

The output directory must be new. Preserve existing runs and selected checkpoints; do not restart merely because the SSH hostname proxy fails. Model weights and original raw data remain outside Git. The direct SSH job receipt identifies the original PID and log.
