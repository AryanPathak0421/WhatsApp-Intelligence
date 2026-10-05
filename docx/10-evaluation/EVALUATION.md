# Evaluation: suites, benchmarks and measured results

Rule: a number is reported only with what it was measured on. "In-sample" means the rules/thresholds were tuned on the same data.

## 1. Automated test suites (run on every change)

| Suite | Command | Count | Covers |
|---|---|---|---|
| AI engine | `cd ai-engine && PYTHONPATH=. .venv/Scripts/python -m pytest -q` | 175 pass | parser, rules, extractors, Q&A, sentiment, periodic summaries, completion rule, analytics, search, summaries, reports, registry, annotation tools |
| Backend | `cd backend && TEST_DATABASE_URL=... TEST_SKIP_MIGRATE=1 npx vitest run` | 83 pass (11 files) | auth, e2e, failures, overview, request log, insights endpoints, status/readiness, SSE, WhatsApp webhook, retention/erasure, watched-folder import and zip reader |
| Frontend | `cd frontend && npx vitest run` and `npx tsc -b --noEmit` | 12 pass, typecheck clean | formatting/helpers, SSE parser |
| Assistant | `cd assistant && python -m pytest -q` | 57 pass | policy, actions, confirmations, injection (worst-case stub), RAG, API, harness, voice |
| Real-backend contract | `assistant/scripts/live_smoke.py` | PASS | create project/task verified by read-back, complete via confirmation, delete refused |

The backend tests need a PostgreSQL (the docker `wa_intel_test` database, or the embedded dev server: `scripts/dev/embedded-pg/start.mjs`).

## 2. Classification of messages (rules vs. learned model), one real chat

Reference labels are **model-made (reviewer "claude"), single project** = silver, not ground truth. Numbers describe agreement with those labels on 233 messages of the anonymised HG chat.

| System | Agreement |
|---|---|
| Rule proposals at the start | 51.5% |
| After Hinglish/Devanagari requirement/feedback/ask-client rules | 66.5% |
| After task/payment/meeting/question rules and TASK_PENDING merged into TASK | **69.5%** |
| Classifier trained on synthetic + silver labels, 5-block CV | 52.8% - 56.2% (best), context variant 42%, synthetic only 32% |
| Hybrid (rules unless confidence <= 0.5, else classifier) | 65.2% |

Caveats: rules were tuned on these same messages (in-sample); the labels are not independent. The learned classifier did **not** beat the rules and was **not deployed**. A human audit sample and kappa between the
labeller and a person are still outstanding. Details: `12-datasets-and-models`.

## 3. Task/status extraction on hand-written unseen chats (`ai-engine/bench/unseen_eval.py`)
Tuned rounds: task recall 100% (8/8) and 80% (4/5), assignee accuracy 100%/80%; **fresh holdout (written after tuning, run before tuning on it): task recall 33% (1/3), assignee 33%, client-pending recall 0%**.
Tiny sets; the honest reading is that generalisation to unseen phrasing is weak.

## 4. Assistant evaluation harness (`assistant/wa_assistant/eval`)
37 cases (EN and Hinglish) in 9 categories scored by **state diff against a sandbox backend**: read 8, write 7, sensitive (confirmation) 4, refuse 5, permission 3, clarify 3, navigate 2, injection 3, general 2.
A case passes only if the expected effect happened and nothing else changed. Safety (any T3 execution, any unexpected change) is reported separately and blocks release.

| Run | Result |
|---|---|
| Oracle (gold script; validates cases and scoring) | 37/37 |
| Worst-case obedient model on 11 attack/refuse/permission cases | 11/11, **0 safety violations, 0 T3 executed** |
| Harness negative tests (never-acts model fails all writes; an extra unrequested write fails the case) | verified |
| **Qwen2.5-7B-Instruct Q4_K_M (real model), 37 cases** | **running; results to be added here and in `private-data/assistant/bakeoff_qwen2.5-7b.json`** |

Observed generation speed on this CPU while other jobs ran: about **1 token/s** (56 tokens in 47 s, prompt eval about 4 tokens/s on short prompts). Expect each agent step to take tens of seconds; a full 37-case run takes hours.
This is the dominant practical limit of the self-hosted assistant on this hardware.

## 5. Question/answer analytics, sentiment, summaries
See `05-ai-nlp-pipeline`: unit tests on hand-written examples (Q&A 8, sentiment 5 incl. 31 labelled examples at >= 85%, periodic 4). **No independent accuracy measurement on real data exists** for these three.

## 6. Not yet measured (do not quote any figure)
Embedding/reranker quality on Hinglish queries, ASR WER/CER, TTS quality, end-to-end voice latency, RAG faithfulness at scale, hallucination rate of the real LLM, load/throughput of the webhook and queue,
failure injection (Redis/DB/LLM down) beyond the unit-level cases, golden set of hundreds of cases (37 exist).
