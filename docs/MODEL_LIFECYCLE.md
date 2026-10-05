# Model lifecycle: label -> train -> evaluate -> promote -> monitor -> roll back

Everything here runs on your own hardware; no external AI service is involved at any step.

## What exists today (and what does not)
| Step | Implemented | Where |
|---|---|---|
| Parse + pseudonymise real chats | yes | `app/parsers/whatsapp.py`, `app/datasets/anonymize.py` |
| Annotate (category, entities, status, assignee, deadline, flags) + active-learning queue | yes | `/annotate` page, `app/annotation/` |
| Check label quality (Cohen's kappa) | yes | `python -m app.evaluation.agreement a.jsonl b.jsonl` |
| Project-level splits (no leakage), synthetic data train/val only | yes | `app/datasets/split.py` |
| Train + evaluate baseline classifier (macro-F1, per-class, confusion, calibration) | yes | `python -m app.training.train_baseline` |
| Fine-tune a local transformer for comparison | yes (CPU: ~27 min for e5-small / 4 epochs) | `python -m app.training.finetune_transformer` |
| Registry with evaluation gate, promotion audit, rollback | yes | `python -m app.training.registry ...` |
| Serve the production model | yes | `MODEL_REGISTRY_DIR` -> `GET /ai/model` shows the serving version; every prediction carries `model_version` |
| Drift monitoring (class mix, language mix, confidence, correction rate) | library + CLI; log is written when `PREDICTION_LOG` is set | `app/monitoring/drift.py` |
| Retraining that consumes human corrections automatically | **no** - corrections are stored (`TrainingExample`, annotation JSONL) but the export -> train -> register loop is manual | |
| NER model, summariser model, transformer in production | **no** - rules + TF-IDF classifier only; embeddings are pretrained, not fine-tuned | |
| Scheduled drift job / alerting | **no** - run the CLI from cron and wire the exit code (3 = drift) to your alerting | |

## The loop
1. **Collect and pseudonymise** real project chats: `python -m app.datasets.anonymize chat.txt chat.anon.txt --map chat.names.json` (keep the map private). See `LABELING_PLAN.md`.
2. **Annotate** in `/annotate`; double-annotate ~10% and run the agreement tool. kappa >= 0.7 or fix the guidelines first.
3. **Split by project** (never by message): `split_projects` gives train/val/test; keep >= 20% of projects as a frozen TEST set that is never trained on and never used to choose rules.
4. **Train**: `python -m app.training.train_baseline` (human-labelled projects are picked up automatically; only they populate `REAL_TEST`). Compare with `finetune_transformer` on the same split.
5. **Register**: `python -m app.training.registry register classifier <version> <model.joblib> <metrics.json>`.
6. **Promote** (never automatic): `python -m app.training.registry promote classifier <version> --by <you> --min-macro-f1 0.75`.
   The gate refuses when: there is no `REAL_TEST` section (synthetic and hand-written-probe scores are not evidence), macro-F1 is below your floor, or it is below the current production model.
   `--force` exists for emergencies and is written to the audit history (`registry.json -> history[].overridden`).
7. **Serve**: set `MODEL_REGISTRY_DIR` on the AI engine; the API reloads when the production pointer changes (no restart). Confirm with `GET /ai/model`.
8. **Monitor**: with `PREDICTION_LOG` set, every classification is logged as `{project, message id, label, confidence, model_version, language}` (never text).
   Weekly: `python -m app.monitoring.drift baseline.jsonl current.jsonl` - flags class-mix PSI > 0.2, language-mix PSI > 0.2, mean confidence drop > 0.10, > 15 points more low-confidence predictions, and (if you pass it) reviewer correction rate > 30%. A flag means *review and consider retraining*, never an automatic change.
9. **Roll back**: `python -m app.training.registry rollback classifier --by <you>` restores the previously promoted version (recorded in the history).

## Evaluation rules that must not be bent
- Report **macro-F1** (classes are imbalanced), per-class F1 and the confusion matrix; accuracy alone is not accepted.
- The test set is real, human-labelled and split by **project**. Anything tuned against it is no longer a test set - keep a second frozen set for each round of rule changes (`docs/PHASE11_TESTING_BENCHMARKS.md` shows how much the numbers move when this is ignored: 99% on own templates vs ~44% task recall on unseen chats).
- Calibrate the active-learning thresholds (auto-accept > 0.95, review 0.70-0.95, annotate < 0.70) on real data; the current values were only sanity-checked on 101 hand-written messages.

## Honest status
No real labelled data has been used yet, so no model has ever passed the gate and the registry is empty: the system serves **rules only** until a classifier earns promotion. That is the intended safe default.
