# Phase 3 - Baseline classifier results

Model: word(1-2) + char_wb(2-5) TF-IDF -> LogisticRegression (class_weight=balanced). Run: `python -m app.training.train_baseline`.
Split: by project. Model selection on validation only; reported numbers come from a model that never saw the evaluated rows.

| Evaluation set | n | Accuracy | Macro-F1 | How to read it |
|---|---|---|---|---|
| Synthetic validation (held-out synthetic projects) | 1899 | 1.000 | 1.000 | **Meaningless.** Templates repeat; the model memorises them. |
| Handwritten probe (101 out-of-template msgs, EN/Hinglish) | 101 | 0.634 | 0.624 | Smoke check of generalisation. Tiny, 4-5 per class, written by the developer, not a benchmark. |
| REAL_TEST (held-out real projects) | 0 | - | - | **Not available yet. No accuracy claim is made.** |

## Findings
- Synthetic-only training gives a large gap (1.00 -> 0.62). Real labelled chats are needed; synthetic is a warm-start only.
- Weakest probe classes: TESTING (0.00), CLIENT_FEEDBACK (0.25), TASK_COMPLETED (0.36) - synthetic phrasing too narrow ("tested successfully" vs "ran the regression suite").
- Confidence is directionally useful on the probe: >=0.85 -> 19/19 correct; <0.50 -> 39% correct (51 msgs). So the 95/70 active-learning lanes
  will route most wrong predictions to humans, but thresholds must be re-calibrated on real data.
- Naive "previous message" context (concatenated into the same TF-IDF) did not help (val 0.89 vs 1.00 on synthetic); needs a proper context
  model (Phase 4: pair encoding in the transformer).

## Next to improve honestly
1. Annotate 15-30 real projects (target >= 5k messages, >= 100 per rare class), double-annotate 10%.
2. Broaden synthetic phrasing (or paraphrase with a local open-weights model) - evaluate only on real/held-out data.
3. Phase 4: fine-tune multilingual encoder (MuRIL / XLM-R / multilingual-e5) and compare on the same REAL_TEST using macro-F1.
