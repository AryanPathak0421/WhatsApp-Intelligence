# Datasets and models

## Language model (assistant)
| Item | Value |
|---|---|
| Model | Qwen2.5-7B-Instruct, GGUF **Q4_K_M** (2 shards: 3.99 GB + 0.69 GB = 4.68 GB) |
| Source | `huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF` (downloaded 2026-10-06 with your approval) |
| Licence | Apache-2.0 (as shown on the model card at download time; re-check before commercial redistribution) |
| Runtime | llama.cpp release b11429 (`llama-b11429-bin-win-cpu-x64.zip`, 19.4 MB, official ggml-org GitHub release), `llama-server --jinja -c 8192 -t 8` |
| Location | `private-data/llm/` (git-ignored) |
| Measured speed here | about 1 token/s generation while other jobs ran (CPU, 15.7 GB RAM); prompt processing a few tokens/s on short prompts, faster with the cached prefix |
| Tool-calling quality | being measured (37-case sandbox bake-off); see `10-evaluation` |
No other model was downloaded. Embeddings default to the dependency-free hashing embedder; the e5-small encoder is used only when `EMBED_MODEL` points to local weights.

## Classifier for message categories (24 labels; `TASK_PENDING` merged into `TASK`)
- Baseline TF-IDF (word + char n-grams) + logistic regression / calibrated SVM, project-level splits, registry with an evaluation gate (`docs/MODEL_LIFECYCLE.md`, `docs/PHASE3_BASELINE_RESULTS.md`).
- Trained on 8,710 synthetic messages (train/val only) and, in `app/training/train_silver.py`, on 233 silver labels from one real chat. **Not deployed:** it scored below the rules (see EVALUATION).
- The rule engine is the production proposer. The classifier is retained for future use once there are ~1,500+ real labels from several chats.

## Datasets
| Set | Origin | Size | Status |
|---|---|---|---|
| Synthetic project chats with gold labels | generated (`app/datasets/synthetic.py`) | 8,710 messages | train/val only; scores on it are optimistic and labelled `SYNTHETIC_ONLY` |
| Hand-written unseen chats with gold | authored | 6 chats | benchmark only (`ai-engine/eval/unseen`) |
| Handwritten probe | authored | small | smoke check |
| **Real chat (HG, anonymised)** | owner's export | 235 labelable messages | labelled by a model (reviewer "claude"); 2 labels by the owner. **Silver, not ground truth** |
| Assistant evaluation cases | authored | 37 | state-diff scored |
| Sentiment examples | authored | 31 | sanity check only |
Private data lives in `private-data/` (git-ignored): raw export, anonymised text, pseudonym map, batch, annotations, LLM files, logs, dev credentials. The anonymiser masks names, phones, emails, URLs, long digits and pasted
passwords/keys; **the HG original still contains a website password and an SMS API key: rotate them.**

## Annotation workflow (`localhost:8000/annotate`)
Batches carry rule proposals, active-learning triage (>0.95 auto-accept, 0.70-0.95 review, <0.70 annotate), 10% double annotation and 10% audit; labels are append-only per reviewer; stats show accept rate overall, per
category and per confidence band; Cohen's kappa between two reviewers (`app/evaluation/agreement.py`). To use the labels as ground truth: have a person label the double-annotation items blind, compute kappa vs. the model labels,
fix the convention disagreements, then train/evaluate with project-level splits.

## What is still needed for real model improvement
1. Human labels on several real chats (target 1,500+ messages), including sentiment and Q&A answers, with double annotation and kappa >= 0.7.
2. A held-out project for REAL_TEST (never used for tuning).
3. Only then: fine-tune a multilingual encoder or LoRA the LLM on tool traces; gate with the registry evaluation.
