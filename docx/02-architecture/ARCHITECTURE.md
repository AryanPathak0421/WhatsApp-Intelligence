# Architecture

Modular monolith with three deployable parts (backend, AI engine, assistant) plus the frontend. Boundaries are kept clean so a part can be split out later, but nothing is
split without a reason (ADR-001/002 in `01-analysis/DECISIONS.md`). Since 2026-10-11 the only source of new messages is the in-app chat; all WhatsApp ingestion was removed (ADR-007).

## Modules inside the backend (`backend/src`)

| Module | Files | Responsibility |
|---|---|---|
| Auth / RBAC | `controllers/auth.ts`, `middlewares/auth.ts`, `utils/permissions.ts` | JWT access + rotating refresh tokens, 6 roles, permission matrix, project membership (404 for non-members) |
| Projects, tasks, analytics, reports, overview | `controllers/*.ts` | CRUD and read models; analytics read the latest `AIAnalysis` snapshots |
| In-app chat | `services/rooms.ts`, `controllers/rooms.ts` | project groups, groups, direct messages; project-group messages mirrored into `ChatMessage`; typing indicator; see `03-ingestion/IN_APP_CHAT.md` |
| Invitations and e-mail | `services/invites.ts`, `services/mailer.ts` | single-use invitation links, member notices over SMTP (disabled without `SMTP_HOST`) |
| Analysis orchestration | `services/analysis.ts`, `services/reanalysis.ts`, `queues/index.ts`, `workers/index.ts` | stored messages -> AI engine -> persist derived rows + snapshots -> notify; debounced scheduling; BullMQ or inline queue |
| Live events | `events/bus.ts`, `controllers/events.ts` | in-process or Redis pub/sub bus; SSE stream with per-project (analysis) or per-member (chat) delivery |
| Status | `controllers/status.ts` | `/health`, `/ready`, `/queue/status`, `/ai/status` |
| Retention | `services/retention.ts`, `controllers/retention.ts` | per-project policy, purge, erasure, scheduled sweep |

## AI engine (`ai-engine/app`)

Rule engine and extraction (`intelligence/`: tasks, client pending, requirements, decisions, conflicts, bugs, commitments, risks, **qa**, **sentiment**,
**completion** rule lives in the assistant-independent engine), analytics (progress, health), summarization (`executive`, **`periodic`**), search (`search/semantic.py`),
knowledge graph, reports, training/registry/monitoring, annotation tool. `intelligence/pipeline.py:analyze()` returns one dictionary that the backend persists.
The WhatsApp-export parser and the .txt file endpoints remain only as offline evaluation/annotation tooling for the benchmark datasets; `POST /ai/parse` was removed and the backend never calls the parser.

## Assistant (`assistant/wa_assistant`)

Agent loop, policy engine, tool registry, executor (acts with the user's token), pending confirmations, audit, document RAG, voice. See `07-assistant`.

## Database migrations of note

| Migration | Change |
|---|---|
| `20261006000000_whatsapp_sources` | table `WhatsappSource` (dropped again by `20261011010000`) |
| `20261006010000_project_retention` | `Project.retentionDays` (nullable) |
| `20261006020000_google_drive` | tables `GoogleConnection`, `DriveImport` (dropped again by `20261011010000`) |
| `20261009010000_inapp_chat` | `ChatRoom`, `RoomMember`, `RoomMessage` |
| `20261010010000_chat_invites` | `ChatInvite` (token hash, e-mail, room, inviter, expiry, accepted/revoked) |
| `20261011010000_remove_whatsapp_import` | drops `WhatsappSource`, `GoogleConnection`, `DriveImport`; `ChatMessage`/`ChatUpload` rows from earlier imports are kept and still analysed |

New derived outputs (Q&A, sentiment, periodic summaries) are stored as `AIAnalysis` snapshots with kinds `QA`, `SENTIMENT`, `PERIODIC`, so they needed no new tables.

## Cross-cutting rules

1. Raw message text is never modified; AI output lives in separate rows with `sourceMessageIds`.
2. Counts, rates, dates, response times are plain code; models only classify or generate text.
3. Every derived item carries evidence (message ids) and a confidence or `needs_review` flag.
4. Authorization is enforced in the backend on every request; the frontend only hides things.
5. Timestamps are wall-clock-as-UTC in the project timezone (same convention for in-app messages and messages from earlier imports).
6. Errors shown to users are sanitised; logs contain no message text or query strings.
