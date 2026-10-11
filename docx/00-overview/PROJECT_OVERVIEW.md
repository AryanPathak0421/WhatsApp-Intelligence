# Project overview

**What it is:** a self-hosted platform where a team holds its project conversations in the application's own **in-app chat** (project groups, groups, direct messages,
e-mail invitations) and gets structured, evidence-linked project intelligence from the project groups (tasks, decisions, risks, questions, tone, summaries,
progress/health), shown in a dashboard, searchable, and with an assistant that can answer questions and act in the application under the signed-in user's
permissions. One company, no external AI services. WhatsApp is no longer ingested in any form (ADR-007 in `01-analysis/DECISIONS.md`); messages stored by the
former import are kept and still analysed.

The [architecture PDF](WhatsApp_Platform_Architecture.pdf) predates the removal of WhatsApp ingestion (2026-10-11); where it differs, this folder's Markdown is current.

## Services

| Service | Tech | Port (dev) | Role |
|---|---|---|---|
| Frontend | React 19, Vite, Tailwind, TanStack Query | 5199 | dashboard, team chat, assistant panel, live updates |
| Backend API | Node, Express, Prisma, PostgreSQL | 4000 | auth, RBAC, projects, in-app chat and invitations (SMTP), analysis orchestration, analytics endpoints, retention, SSE |
| Worker | BullMQ (or in-process fallback) | - | runs analysis jobs |
| AI engine | Python FastAPI | 8000 | rule/ML analysis, search index, summaries, reports; offline evaluation and annotation tools (incl. the WhatsApp-format parser, used only for benchmark datasets) |
| Assistant | Python FastAPI | 8100 | tool-calling agent, policy engine, document RAG, voice endpoint |
| LLM server | llama.cpp `llama-server`, Qwen2.5-7B-Instruct Q4_K_M | 8081 | language model for the assistant (CPU) |
| Database | PostgreSQL 16 (+ pgvector in production; embedded Postgres in dev) | 15433 dev | all application data |
| Redis | optional in dev | 6379 | BullMQ and cross-process live events |

## Data flow

```
in-app chat (project group) -> backend (RoomMessage + mirrored ChatMessage) -> debounced job (ANALYSIS_DEBOUNCE_MS) -> AI engine analysis
  -> derived rows + snapshots (tasks, decisions, risks, Q&A, tone, summaries, progress, health) -> PostgreSQL
  -> live event (SSE) -> dashboard refetches          assistant -> tools -> backend API (as the user) -> verified result
```

## Status (honest)

| Area | State | Where documented |
|---|---|---|
| Rule-based extraction, progress/health, search, reports, re-analysis of stored messages | Done, tested | `docs/` phases, `05`, `06` |
| Question/answer analytics, sentiment/urgency, daily/weekly/monthly summaries | Done, tested; quality measured only on author-written/small data | `05` |
| Project-completion rule | Done, tested on one real (exported) chat used as evaluation data | `05` |
| In-app chat: project groups (analysed), groups, direct messages (never analysed), e-mail invitations | Done, tested (rooms 13, invites 8); SMTP delivery depends on the configured server | `03` |
| WhatsApp ingestion (Cloud API webhook, export upload, watched folder, Google Drive) | **Removed** (2026-10-11, ADR-007) | `01/DECISIONS` |
| Live dashboard and chat events (SSE) with polling fallback | Done, tested | `04` |
| Health/readiness/queue/AI status endpoints | Done, tested | `02`, `11` |
| Retention policy, purge, erasure | Done, tested | `09` |
| Assistant (tools, policy, confirmations, audit, RAG with citations) | Done, tested with doubles and a sandbox backend; real-model bake-off done: 73% on 37 sandbox cases, 0 safety violations (see 10-evaluation) | `07`, `10` |
| Voice | Endpointing and endpoint built; **no speech model installed**, unmeasured | `08` |
| Multi-tenancy | **Not in scope** (single-company decision) | `01/DECISIONS` |
| RabbitMQ / Kafka | **Not in scope** (BullMQ kept) | `01/DECISIONS` |
| Fine-tuning, human-labelled datasets at scale | Not started; labels so far are model-made | `12` |

## Where to start

Run the stack: `scripts/dev/dev-up.ps1` (see `11-deployment-and-ops/OPERATIONS.md`). Log in at http://localhost:5199 (dev credentials in `private-data/dev-admin.txt`).
