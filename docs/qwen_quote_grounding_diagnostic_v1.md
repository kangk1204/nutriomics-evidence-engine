# Exact quotation grounding: separate post-hoc diagnostic

The original strict full750 score remains F1=0 (TP0/FP5/FN3761). This separate parser was developed after that score was exposed. It must not replace the original measurement or be represented as an untouched evaluation.

The supplied complete quotation must appear exactly once in unchanged source text and contain both native CHEMICAL/GENE argument spans. Its deterministic offsets then pass through the unchanged strict parser, including negation rejection. Original six JSON fields are supported; nullable numeric spans are a diagnostic accommodation. Generation-schema and API grounding validation have not been performed. Malformed/extra JSON, ambiguous quotation, missing quotation, wrong entities and unsupported labels abstain.

All750 documents remain in the denominator. Accepted relations: 150; reconstructed offsets: 145. Strict exact tuple TP=43, FP=107, FN=3718; precision=0.286667, recall=0.011433, F1=0.021989. Official upstream scoring is a separate subsequent step because its known matrix-boundary indexing issue can change counts.

Gold relations were opened only after predictions and their grounding lock were written. Prediction SHA256: `fc1f8a722099f875062752049420bbb6d80a77c4c7150cfe3f3f2fb1802359f4`. Grounding lock SHA256: `e7f84122adef96b1484336dd7db4d09f45a7802b17bafe4bafbd2cec3c7ffaaf`. Semantic entailment, expert approval, food accuracy, binding affinity and therapeutic effect are unvalidated. Exact text grounding alone is not proof of the relation label or causality. No model training or gold-guided parameter search occurred.

The pinned unmodified official evaluator completed in 155.3 seconds: TP=43, FP=107, FN=3715, precision=0.286666667, recall=0.011442257, F1=0.022006141. Exact parity is false: its known upstream document-boundary matrix collisions remove3 native gold relations, changing FN/recall/F1 while TP/FP agree. All original evaluator inputs, immutable copies and upstream source hashes were unchanged. Both score definitions remain separately recorded.

The independent parser also rejects ambiguous duplicate JSON object keys. Five raw responses contain these; one already failed original JSON parsing, so four additional documents abstain. This conservative diagnostic policy was implemented before its score was computed; no competing policy was selected from scores. The original strict parser and750-result archive are unchanged.
