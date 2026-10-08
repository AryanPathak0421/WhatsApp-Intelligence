# Project overview

**What it is:** a self-hosted platform that turns WhatsApp project chats into structured, evidence-linked project intelligence (tasks, decisions, risks, questions,
tone, summaries, progress/health), shows it in a dashboard, lets people search it, and offers an assistant that can answer questions and act in the application
under the signed-in user's permissions. One company, no external AI services.

## Services

| Service | Tech | Port (dev) | Role |
|---|---|---|---|
| Frontend | React 19, Vite, Tailwind, TanStack Query | 5199 | dashboard, assistant panel, live updates |
| Backend API | Node, Express, Prisma, PostgreSQL | 4000 | auth, RBAC, projects, import, analysis orchestration, analytics endpoints, webhook, retention, SSE |
| Worker | BullMQ (or in-process fallback) | - | runs analysis jobs |
| AI engine | Python FastAPI | 8000 | parsing, rule/ML analysis, search index, summaries, reports, annotation tool |
| Assistant | Python FastAPI | 8100 | tool-calling agent, policy engine, document RAG, voice endpoint |
| LLM server | llama.cpp `llama-server`, Qwen2.5-7B-Instruct Q4_K_M | 8081 | language model for the assistant (CPU) |
| Database | PostgreSQL 16 (+ pgvector in production; embedded Postgres in dev) | 15433 dev | all application data |
| Redis | optional in dev | 6379 | BullMQ and cross-process live events |

## Data flow

```
export file / Cloud API webhook -> backend (validate, dedupe, store messages) -> job queue -> AI engine analysis
  -> derived rows + snapshots (tasks, decisions, risks, Q&A, tone, summaries, progress, health) -> PostgreSQL
  -> live event (SSE) -> dashboard refetches          assistant -> tools -> backend API (as the user) -> verified result
```

## Status (honest)

| Area | State | Where documented |
|---|---|---|
| Chat parsing, incremental import, rule-based extraction, progress/health, search, reports | Done, tested | `docs/` phases, `05`, `06` |
| Question/answer analytics, sentiment/urgency, daily/weekly/monthly summaries | Done, tested; quality measured only on author-written/small data | `05` |
| Project-completion rule | Done, tested on one real chat | `05` |
| Watched-folder import of phone exports (.txt/.zip) with stability, duplicate and busy-project guards | Done, tested (11); not tested against a real Google Drive sync | `03` |
| WhatsApp Cloud API webhook (signature, mapping, idempotency, debounced analysis) | Done, tested with signed fixtures; **never exercised against Meta** | `03` |
| Live dashboard events (SSE) with polling fallback | Done, tested | `04` |
| Health/readiness/queue/AI status endpoints | Done, tested | `02`, `11` |
| Retention policy, purge, erasure | Done, tested | `09` |
| Assistant (tools, policy, confirmations, audit, RAG with citations) | Done, tested with doubles and a sandbox backend; real-model bake-off done: 73% on 37 sandbox cases, 0 safety violations (see 10-evaluation) | `07`, `10` |
| Voice | Endpointing and endpoint built; **no speech model installed**, unmeasured | `08` |
| Multi-tenancy | **Not in scope** (single-company decision) | `01/DECISIONS` |
| RabbitMQ / Kafka | **Not in scope** (BullMQ kept) | `01/DECISIONS` |
| Fine-tuning, human-labelled datasets at scale | Not started; labels so far are model-made | `12` |

## Where to start

Run the stack: `scripts/dev/dev-up.ps1` (see `11-deployment-and-ops/OPERATIONS.md`). Log in at http://localhost:5199 (dev credentials in `private-data/dev-admin.txt`).
