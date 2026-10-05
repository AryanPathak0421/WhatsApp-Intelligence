# Dataset Strategy (training + testing)

Status: proposal. Dataset names, sizes and licenses below are from memory and
have NOT been verified in this session. Verify each license before any
commercial use (this is a company product).

## Key fact

No public dataset has WhatsApp-style, Hinglish, IT-project chats labelled with
our 24 categories, task status, assignee, deadline and client-pending.
So there is no single "best dataset". The best approach is a 3-layer mix, and
the **test set must be real, human-labelled chats from your own projects**.

## Layer 1 - Public data (transfer / pretraining / auxiliary tasks)

| Need | Dataset | Use |
|---|---|---|
| Hinglish language ability | L3Cube HingCorpus / HingBERT, MuRIL, XLM-R, multilingual-e5 | Pretrained encoders (no data needed) |
| Hinglish NER / LID | GLUECoS, LinCE | Fine-tune NER + language-ID heads |
| Roman <-> Devanagari | Aksharantar (AI4Bharat), Dakshina | Hinglish normalisation / transliteration |
| Task status, priority, type, bug lifecycle | Public Jira Dataset (Montgomery et al., 16 repos, ~2.7M issues) | Status-transition language, bug vs task, priority, story points (weights) |
| Story-point / complexity | Choetkiertikul "deep-se" story point data | Task weight model |
| Developer chat | Slack dev chats w/ disentanglement (Chatterjee et al.), Gitter (GitterCom), DISCO (Discord), Ubuntu IRC | Thread/conversation linking, dev-chat register |
| Action items / commitments | AMI Meeting Corpus, Enron emails | Commitment + action-item detection |
| Contradiction | MNLI, XNLI (has Hindi), ANLI | Pretrain contradiction classifier, then adapt |
| Chat summarization | SAMSum (CC BY-NC-ND: non-commercial, check!), DialogSum, QMSum | Summarizer warm start |

## Layer 2 - Synthetic project chats (bootstrap labels)

Template + slot generator (Python, no external API): roles x modules x
statuses x Hindi/English/Hinglish phrasing x typos/emoji/abbreviations,
emitting WhatsApp-format `.txt` with gold labels (category, assignee,
deadline, status, task-thread id). Optionally paraphrase with a *local*
open-weights model (self-hosted, so privacy rule holds).
Use ONLY for training/augmentation. Never for the test set (inflated scores).

## Layer 3 - Your real chats (the gold standard)

1. Export 15-30 past project groups (mask phones/names/secrets).
2. Pre-label with rules + Layer 1/2 models, humans correct in the annotation tool.
3. Double-annotate ~10% of messages; report Cohen's kappa. Target >= 0.7.
4. Active learning (95 / 70 thresholds from the spec) grows the set over time.

## Split (no leakage)

Split by PROJECT, never by message:
- Train: ~60% of projects (+ all Layer 1/2 data)
- Validation: ~20% of projects
- Test: ~20% of projects, real + human-gold only, frozen, never trained on
- Also hold out one project of each type (e-commerce, mobile app, etc.)
- Task-resolution/progress are evaluated per project against manually reviewed values.

## Minimum viable sizes (rule of thumb)

- Classifier baseline (TF-IDF + LR): ~3-5k labelled messages, rare classes >= 100 each
- Transformer fine-tune: ~10k+ messages, or fewer with Layer 1/2 warm start
- NER: ~2k messages with entity spans
- Task linking / conflicts: ~500 labelled thread/pair examples each

Metric: Macro-F1 (class imbalance), plus per-class F1 and confusion matrix.

## Risks

- Synthetic-only results will look great and fail in production. Report scores on real test data only.
- Licenses (SAMSum, XNLI are non-commercial) may block commercial deployment of derived weights.
- Python 3.14 here: some ML wheels (torch, spaCy, faiss) may lag. Use Python 3.11/3.12 venv for ai-engine.
- Machine has no NVIDIA GPU: plan CPU-friendly models (MiniLM, multilingual-e5-small, DistilBERT/MuRIL-base with ONNX).
