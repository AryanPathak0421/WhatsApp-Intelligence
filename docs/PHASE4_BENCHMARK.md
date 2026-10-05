# Phase 4 - Transformer fine-tuning (partial, honest)

Script: `python -m app.training.finetune_transformer --model <hf-id> [--ctx]` (CPU, project-level split, selection on validation only).
Run so far: **multilingual-e5-small** (118M params), 4 epochs on 6.8k synthetic messages (~27 min on this 12-core CPU, no GPU).

| Model | Synthetic val macro-F1 (inflated) | Handwritten probe macro-F1 | Probe acc | REAL_TEST | CPU ms/msg |
|---|---|---|---|---|---|
| TF-IDF + LogReg (Phase 3) | 1.000 | 0.624 | 0.634 | none | <1 |
| multilingual-e5-small fine-tuned | 1.000 | 0.578 | 0.584 | none | ~34 (loaded machine) |

Finding: on this tiny out-of-template probe the fine-tuned encoder did NOT beat the baseline; both memorise the synthetic templates and generalise
at ~0.6. With 101 probe messages the difference is within noise. **The bottleneck is training data, not model size.**
The queued larger models (distilbert-multilingual, MuRIL-base, XLM-R-base; ~1-2 h each on CPU) were stopped to free the CPU: running them on the
same synthetic data would not be informative. Re-run `run_benchmark.sh` once real annotated chats exist (REAL_TEST will then be reported).
