# ai-engine

```bash
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt   # Python 3.11/3.12 recommended
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m app.datasets.synthetic --projects 40 --out data/synthetic   # training data only
.venv/Scripts/python -m uvicorn app.api.main:app --port 8000                       # then open /annotate
```

- `app/parsers/whatsapp.py` streaming parser (Android/iOS/US, 12h/24h, multiline, system/media/deleted, phone senders,
  utf-8/16/cp1252, auto date-order detection with ambiguity warning). Original text always kept in `raw_text`.
- `app/annotation/` append-only JSONL annotation store + active-learning triage (>0.95 accept, 0.70-0.95 review, <0.70 queue).
- `app/datasets/synthetic.py` synthetic EN/Hinglish/Devanagari chats with gold labels. **Never use as test data.**
- `app/datasets/split.py` project-level (leak-free) splits.

## Phase 3
`python -m app.training.train_baseline` trains/evaluates the baseline (see docs/PHASE3_BASELINE_RESULTS.md). Probe set: eval/probe_handwritten.jsonl.

## Phase 5-6
`POST /ai/analyze` returns tasks, client pending, requirement changes, conflicts, bugs, commitments, risk, progress, health, contribution, sales, communication. See docs/PHASE5_INTELLIGENCE.md and docs/PHASE6_ANALYTICS.md. Score against gold: `python -m app.evaluation.eval_intelligence`.

## Phase 7-8
`/ai/index`, `/ai/search`, `/ai/graph`, `/ai/summarize`, `/ai/report?format=pdf|xlsx|csv|json`. See docs/PHASE7_SEARCH_GRAPH.md and docs/PHASE8_SUMMARIZATION_REPORTS.md.
