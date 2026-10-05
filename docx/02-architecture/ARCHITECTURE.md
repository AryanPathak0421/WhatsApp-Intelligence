# Architecture

Modular monolith with three deployable parts (backend, AI engine, assistant) plus the frontend. Boundaries are kept clean so a part can be split out later, but nothing is
split without a reason (ADR-001/002 in `01-analysis/DECISIONS.md`).

## Modules inside the backend (`backend/src`)

| Module | Files | Responsibility |
|---|---|---|
| Auth / RBAC | `controllers/auth.ts`, `middlewares/auth.ts`, `utils/permissions.ts` | JWT access + rotating refresh tokens, 6 roles, permission matrix, project membership (404 for non-members) |
| Projects, tasks, analytics, reports, overview | `controllers/*.ts` | CRUD and read models; analytics read the latest `AIAnalysis` snapshots |
| Analysis orchestration | `services/analysis.ts`, `queues/index.ts`, `workers/index.ts` | upload -> store messages -> call AI engine -> persist derived rows + snapshots -> notify; BullMQ or inline queue |
| Ingestion (webhook) | `services/whatsapp.ts`, `controllers/whatsapp.ts` | signed Cloud API events -> unified messages -> `ChatMessage`; conversation-to-project mapping |
| Live events | `events/bus.ts`, `controllers/events.ts` | in-process or Redis pub/sub bus; SSE stream with per-project authorization |
| Status | `controllers/status.ts` | `/health`, `/ready`, `/queue/status`, `/ai/status` |
| Retention | `services/retention.ts`, `controllers/retention.ts` | per-project policy, purge, erasure, scheduled sweep |

## AI engine (`ai-engine/app`)

Parsers, rule engine and extraction (`intelligence/`: tasks, client pending, requirements, decisions, conflicts, bugs, commitments, risks, **qa**, **sentiment**,
**completion** rule lives in the assistant-independent engine), analytics (progress, health), summarization (`executive`, **`periodic`**), search (`search/semantic.py`),
knowledge graph, reports, training/registry/monitoring, annotation tool. `intelligence/pipeline.py:analyze()` returns one dictionary that the backend persists.

## Assistant (`assistant/wa_assistant`)

Agent loop, policy engine, tool registry, executor (acts with the user's token), pending confirmations, audit, document RAG, voice. See `07-assistant`.

## Database changes made in this iteration (additive migrations only)

| Migration | Change |
|---|---|
| `20261006000000_whatsapp_sources` | table `WhatsappSource` (phoneNumberId + conversationKey -> project, carrier upload, counters); unique on (phoneNumberId, conversationKey) |
| `20261006010000_project_retention` | `Project.retentionDays` (nullable) |

No existing table was altered destructively. New derived outputs (Q&A, sentiment, periodic summaries) are stored as `AIAnalysis` snapshots with kinds `QA`, `SENTIMENT`,
`PERIODIC`, so they needed no new tables.

## Cross-cutting rules

1. Raw message text is never modified; AI output lives in separate rows with `sourceMessageIds`.
2. Counts, rates, dates, response times are plain code; models only classify or generate text.
3. Every derived item carries evidence (message ids) and a confidence or `needs_review` flag.
4. Authorization is enforced in the backend on every request; the frontend only hides things.
5. Timestamps are wall-clock-as-UTC in the project timezone (same convention for exports and webhooks).
6. Errors shown to users are sanitised; logs contain no message text or query strings.
