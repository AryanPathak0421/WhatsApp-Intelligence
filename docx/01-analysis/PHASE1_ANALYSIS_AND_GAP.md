# Phase 1: existing-system analysis, WhatsApp feasibility, and gap analysis against the "Ultimate Master Prompt"

> **Historical document.** WhatsApp ingestion (export import, watched folder, Google Drive import, Cloud API webhook) was later **removed** (2026-10-11, ADR-007 in [DECISIONS](DECISIONS.md)); the product now uses its own in-app chat ([IN_APP_CHAT](../03-ingestion/IN_APP_CHAT.md)). The analysis below is kept unchanged as the record of what was found and decided at the time.

Scope: analysis and design only. **No application code was changed for this document.** Every statement about the repository comes from reading it; statements
about WhatsApp come from Meta's current developer documentation (links in section 3). Items I could not verify are marked **unverified**.

## 0. Findings that change the plan (read first)

1. **The official WhatsApp API cannot ingest the groups this product is used for.** The Cloud API *Groups API* only works for groups **created by the business
   through the API** (invite-only, **max 8 participants**, requires an **Official Business Account**, not available for WhatsApp Business-app numbers). It does
   **not** read existing consumer groups, and messages from group chats are **excluded from history sync**. So "Official API → webhook → existing HG group" is
   not possible; the authorized path for existing groups remains the **one-time export + incremental re-import** that already exists. See section 3.
2. **Much of the master prompt already exists** (parsing, incremental import, task/decision/conflict/commitment/risk extraction, hybrid search, summaries, reports,
   RBAC, audit, model registry, drift monitor, dashboard, an assistant with tools/RAG/confirmation). The real gaps are listed in section 2, not "everything".
3. **RabbitMQ is a replacement decision, not an addition.** The system already runs on BullMQ + Redis with retries, backoff, id-based de-duplication and a
   no-Redis inline mode. Section 5 explains when RabbitMQ is worth it and recommends keeping BullMQ behind an interface until a concrete need appears.
4. **There is no tenant (organization) concept.** Isolation today is per project via membership. Real multi-tenancy is a cross-cutting migration (every table and
   every query) and should be decided deliberately (section 6).
5. **No real LLM is running yet.** A 7B model download is in progress; nothing about LLM tool-calling quality, ASR or TTS is measured.

## 1. Existing architecture (as found)

### Frontend (`frontend/`)
React 19, Vite 8, TypeScript, Tailwind 4, React Router 7 (routes under `p/:projectId/*`, lazy loaded), TanStack Query 5 for server state, Axios with an
interceptor that attaches the access token and performs a single-flight refresh (refresh tokens are single use), react-hook-form + zod, Recharts. Pages:
Executive, Projects, ProjectDashboard, ChatAnalysis, Tasks, Team, ClientPending, Sales, Risks, Timeline, Reports, Analytics, Settings, Login. Permission-aware
navigation (`can(action)`), dark mode, an assistant chat panel (new). Auth: access token in `sessionStorage`, refresh token in `localStorage`. 10 unit tests.

### Backend (`backend/`)
Node + Express 4 + TypeScript, Prisma 6 on PostgreSQL 16 (pgvector image), zod validation, helmet, request log without query strings or bodies. Controllers:
auth, projects, chat (upload, reanalyze, analysis status), tasks, analytics (progress, health, team, sales, client-pending, risks, conflicts, timeline, insights,
summary, notifications, audit), overview (executive, users), reports. Services: `analysis.ts` (orchestrates the AI engine and persists results), `aiClient.ts`.
Auth: JWT access (15 min) + rotating refresh tokens, bcrypt; first registered user becomes SUPER_ADMIN. Authorization: role-permission matrix
(`utils/permissions.ts`, 6 roles) **plus** project membership (a project you cannot see answers 404). Field encryption AES-256-GCM for uploads and phone numbers.
Background jobs: BullMQ queue `wa-analysis` with 2 attempts and exponential backoff, or an inline in-process queue when `REDIS_URL` is absent.
Tests: auth, e2e, failures, overview, request-log suites.

### Database (`backend/prisma/schema.prisma`, 849 lines)
Models: User, RefreshToken, Client, Project, ProjectMember, ChatUpload, ChatParticipant, **ChatMessage** (deterministic ids `<projectId>:<hash>`, wall-clock-as-UTC
timestamps), MessageEnrichment, **MessageEmbedding** (pgvector), ProjectModule, Task, TaskHistory, TaskAssignment, ClientPendingItem, SalesActivity, Requirement,
RequirementChange, **Decision**, Meeting, Commitment, Deadline, Bug, **Conflict**, Risk, ProjectEvent, ProjectProgress, ProjectHealth, **Insight**, AIAnalysis,
AnalysisJob, Report, Notification, **AuditLog**, ChangeLog, **ModelVersion**, TrainingExample. Evidence is stored as source message ids on derived rows.
No `organization` table or tenant column exists.

### AI (`ai-engine/`, Python FastAPI, self-hosted, no external API)
Parser (multi-format WhatsApp exports), rule engine (EN/Hinglish/Devanagari), role inference, task/client-pending/requirement/decision/conflict/bug/commitment/risk
extraction with evidence, project-completion rule, progress and health analytics, hybrid BM25 + dense search with a per-project index, NetworkX knowledge graph,
evidence-bound template summaries and reports, TF-IDF/LR baseline classifier + registry with an evaluation gate, drift monitor (PSI), annotation tool with
active-learning triage, pre-labelling, Cohen's kappa. 158 tests. **No generative LLM is used today.**
`assistant/` (new): tool registry with risk tiers, policy engine, executor acting with the user's token, verification, pending confirmations, audit, RAG over
papers/documents with citation checking, evaluation harness (37 cases), voice endpointing. 57 tests.

### Deployment
`docker-compose.yml`: postgres (pgvector), redis, backend, worker, edge (nginx TLS, rate limits), internal no-internet network; backup/restore scripts (restore
tested); CI workflow (never run); `.env.example`; docs. Local dev currently uses an embedded Postgres because Docker Desktop is not running.

## 2. Gap analysis against the master prompt

Legend: **Done** built and tested | **Partial** exists but incomplete | **Missing** | **Blocked** cannot be done as specified | **Decision** needs your call.

| Spec area | Status | Notes |
|---|---|---|
| 4 Existing-system analysis | Done | this document |
| 5 Modular monolith, clear boundaries | Done | backend + ai-engine + assistant; keep it |
| 6-8 Authorized WhatsApp ingestion, capability audit, historical strategy | **Blocked / Partial** | official API cannot read existing groups (section 3); export + incremental import exists |
| 9-11 RabbitMQ (+ Kafka later) | **Decision** | BullMQ in place; see section 5 |
| 12 Redis | Partial | used by BullMQ only; no cache/rate-limit/locks use yet (nginx rate-limits at the edge) |
| 13 Unified message schema | Partial | ChatMessage exists; no `source`, conversation, media, reaction or reply tables |
| 14 Entities | Partial | most derived entities exist; missing: organizations, whatsapp_accounts, conversations/members, message_media/reactions/replies, questions/answers, topics, sentiments, summaries as tables, processing_jobs (AnalysisJob exists), evaluation_results |
| 15 Multi-tenancy | **Missing / Decision** | per-project isolation only |
| 16 Incremental processing | Partial | import is incremental and idempotent; analysis re-runs over the whole project (cursor-based incremental analysis is missing) |
| 17 NLP pipeline | Partial | tasks, decisions, conflicts, topics, risks exist; **missing:** sentiment/frustration/urgency, question/answer pairing with response times, PII detection at ingest, intent classification beyond the 24-label set |
| 18 Hinglish, keep original text | Done | originals never modified; `normalizedText`/language stored in enrichments (verify field coverage) |
| 19-20 Task / decision extraction with source ids | Done (quality varies) | measured agreement with labelled data is modest (see MODEL_LIFECYCLE, labels are model-made) |
| 21 Question/answer analytics | **Missing** | |
| 22 Conflict detection, evidence-based wording | Done | |
| 23 Sentiment | **Missing** | needs a multilingual model and an evaluation set |
| 24 Topics | Partial | fixed topic groups; dynamic topic discovery missing |
| 25 Hierarchical summaries (daily/weekly/monthly) | Partial | project summaries and reports exist; time-bucketed hierarchy missing |
| 26-29 Chatbot, advanced RAG, embeddings, reranking | Partial | assistant + hybrid search exist; **no generative LLM running, reranker is lexical, embedding models not benchmarked on Hinglish** |
| 30-31 Research KB | Partial | ingestion + citation checking built; no real corpus, review document is from memory (verify) |
| 32-34 Datasets, custom domain set, training strategy | Partial | synthetic data (train/val only), one real chat with model-made labels; **human labels still needed** |
| 35-37 Voice | Partial | endpointing/barge-in and WAV endpoint built; no ASR/TTS model, no UI mic, no streaming |
| 38-44 Application control, permissions, risk, state, planning, verification | Done (assistant) | tiers, confirmations, user-token execution, read-back; multi-step planning is a plain loop, no plan display |
| 45 Hallucination control | Partial | citation validation, abstention built; faithfulness measured only on a tiny sandbox |
| 46 Memory | Partial | conversation memory only; no long-term preferences/expiry/deletion UI |
| 47-48 Security, untrusted data | Partial | injection defences tested against a worst-case stub; **not tested with a real model**; no SSRF surface yet (no outbound fetches) |
| 49 Dashboard | Partial | project dashboards exist; org-level group analytics and AI-insights page need the new schema |
| 50 Real-time dashboard | **Missing** | no WebSocket/SSE; polling only |
| 51 Source traceability | Done | evidence ids on derived rows and a UI component |
| 52 Deterministic vs AI | Done | counts, dates, aggregates are code |
| 53 Model router | Missing | premature until two models exist |
| 54 Caching | Missing | |
| 55 Error handling honesty | Done (assistant) | never reports success without verification |
| 56 Observability | Partial | request log, drift monitor; no metrics/queue-depth/token dashboard |
| 57-58 Evaluation, golden set | Partial | 37 assistant cases, benchmark suites; spec asks for hundreds |
| 59-60 Privacy, retention | Partial | encryption of uploads/phones, audit log; **no retention settings, no deletion of derived data, no PII masking in storage** |
| 61 API spec | Partial | see section 8 |
| 62 Chat UI | Partial | panel built; no streaming, stop/regenerate, markdown, file upload, history |
| 63 File support (DOCX/XLSX/CSV/images) | Partial | PDF/MD/TXT/HTML only |
| 64 Controlled self-improvement | Partial | feedback queue + registry/eval gate exist; no review UI |
| 66 Testing | Partial | no RabbitMQ/failure/load tests for the new parts |
| 70-72 Deployment, health | Partial | compose + health exist; `/ready`, `/ai/status`, `/queue/status` missing; assistant and vector-DB services not in compose |

## 3. WhatsApp capability audit (verified against Meta documentation)

| Feature | Officially supported? | What it means here |
|---|---|---|
| New messages **in business-created groups** | **Yes** (Groups API webhooks include `group_id`, sender, type, text) | only for groups the business created |
| Messages in **existing consumer groups** | **No** (no endpoint; groups are created by the business, invite-only) | cannot replace the export workflow |
| Group size | Max **8 participants** per group; up to 10,000 groups per number | too small for typical project groups |
| Eligibility | Requires an **Official Business Account**; not for Business-app numbers or Multi-solution Conversations numbers | procurement/verification work for the customer |
| Historical messages | Business-app coexistence syncs the last **6 months of 1:1 chats**; **group chats are excluded**; group message webhooks carry no history | no group backfill via the API |
| Attachments | Group webhooks carry media messages, but **media asset IDs are not included** in history sync; initial media IDs only for the last 14 days (1:1) | media download for groups is unverified; treat attachments as metadata only |
| Message updates (edit/delete) | Group messages cannot be edited or deleted through the Groups API; unsupported types return error 130501 | |
| Reactions / replies | **Unverified** for inbound group webhooks | confirm in the API reference before modelling them |
| Automated ingestion | Yes, by webhook, for supported scopes | needs signature verification (`X-Hub-Signature-256`) and idempotency |

Recommended ingestion design (given this):
1. **Existing groups:** keep the authorized export, add an **upload → dedupe → incremental** flow with a clear UI ("import only new messages"); this already exists. A scheduled reminder or a documented routine can reduce the manual burden. No scraping, no session extraction.
2. **New groups the business wants analysed:** create them via the Groups API and ingest by webhook (≤ 8 people; only if the customer qualifies and wants this).
3. **1:1 customer chats:** Cloud API webhooks (and coexistence history) if the customer is on the Business Platform.
Sources: [Groups API](https://developers.facebook.com/docs/whatsapp/cloud-api/groups), [Group messaging](https://developers.facebook.com/documentation/business-messaging/whatsapp/groups/groups-messaging/), [Business app coexistence](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-business-app-users/). Meta changes these rules; re-check before building.

## 4. Target architecture (modular monolith, additive)

```
 Export upload ─┐                       ┌─> Message worker (parse, normalise, dedupe, PII flag)
 Webhook (new) ─┤──> Ingestion module ──┤
 1:1 Cloud API ─┘     (validate, sign)   └─> enqueue per-stage jobs
                                              │ queue abstraction (BullMQ today; RabbitMQ adapter if decided)
              ┌───────────────────────────────┼──────────────────────────────┐
              ▼                               ▼                              ▼
      NLP worker (ai-engine)          Embedding worker               Summary / report worker
   language, intent, topic, tasks,    chunk + embed -> pgvector       hierarchical summaries
   decisions, Q&A, sentiment, conflicts
              └───────────────┬───────────────┴──────────────┬───────────┘
                              ▼                              ▼
                        PostgreSQL (tenant-scoped)       Redis (cache, rate limit, locks)
                              │
                 SSE / WebSocket events ──> Dashboard        Assistant service (RAG, tools, confirm, voice)
```
Boundaries stay as today (Node API, Python AI engine, assistant service). New modules live inside the backend: `ingestion`, `tenancy`, `events`.

## 5. Queue decision: BullMQ (current) vs RabbitMQ vs Kafka vs Redis Streams

| | BullMQ (in place) | RabbitMQ | Kafka | Redis Streams |
|---|---|---|---|---|
| Fit now | Node producers/consumers, one Redis already deployed | Strong: routing, per-queue DLX, ack, priorities, any-language consumers | Overkill below very high volume | Possible, less tooling |
| Retries/backoff/DLQ | Retries + backoff yes; DLQ = failed set | Native DLX + TTL retry queues | Manual | Manual |
| Idempotency | `jobId` de-dup | Needs message ids + consumer dedupe | Consumer-side | Consumer-side |
| Extra ops | none | +1 stateful service, monitoring, upgrades | +cluster | none |
| Python consumers directly | no (via HTTP) | yes (pika/aio-pika) | yes | yes |
**Recommendation:** keep BullMQ behind the `JobQueue` interface now; add a RabbitMQ adapter only when one of these is true: Python workers must consume directly, you need exchange-level fan-out/priority routing, or queue isolation per tenant becomes a requirement. If you want RabbitMQ anyway, the queue set in the spec (`whatsapp.messages`, `ai.embedding`, ... plus `dead-letter`) maps cleanly: topic exchange `ai.*`, one DLX with per-queue retry queues (TTL 5s/30s/5min) and a consumer-side idempotency table keyed by message id. Kafka: not now; the event log can be replayed from PostgreSQL.

## 6. Multi-tenancy (decision needed)

Today: user → project membership. A tenant layer means `organization_id` on **every** tenant-owned table, composite uniqueness, row-level security or mandatory repository scoping, and tests for cross-tenant access. Two options:
- **A (recommended if SaaS is real):** add `Organization`, `organization_id` NOT NULL via a migration with backfill to one default org, enforce with PostgreSQL RLS (`SET app.org_id` per request) so a missed `WHERE` cannot leak.
- **B (single company):** keep project-level isolation, defer tenancy.
This is the most invasive item in the document; it should not be started until you confirm SaaS is a goal.

## 7. Schema delta (additive migrations only, nothing destructive)

Existing tables map onto most of the spec: `ChatMessage` (messages), `ChatParticipant` (conversation members/senders), `MessageEnrichment`, `MessageEmbedding`, `Task`, `Decision`, `Conflict`, `Insight`, `AnalysisJob` (processing_jobs), `AuditLog`, `ModelVersion`.
New: `Organization`, `WhatsappAccount`, `Conversation`, `ConversationMember`, `MessageMedia`, `MessageReaction`, `MessageReply` (or `replyToId` on ChatMessage), `Question`/`Answer`, `Topic`, `Sentiment`, `Summary` (daily/weekly/monthly, with `sourceMessageIds[]`), `ProcessingCursor` (last processed id/timestamp per project and stage), `EvaluationResult`, `RetentionPolicy`, `IdempotencyKey`. Every derived row keeps `sourceMessageIds[]`. Raw text stays untouched; PII flags are separate columns.

## 8. API delta

Existing under `/api`: auth, projects, chat upload/reanalyze/analysis, tasks, analytics, reports, overview. Assistant service (`/assistant/*`): chat, confirm, cancel, pending, voice, documents, feedback, health.
To add: `GET/POST /api/webhooks/whatsapp` (verify token + HMAC signature, 200 fast, enqueue only), `GET /api/conversations`, `GET /api/conversations/:id/messages` (cursor), `GET /api/analytics/overview`, `GET /api/analytics/groups/:id`, `GET /api/events` (SSE), `GET /api/ready`, `GET /api/queue/status`, `GET /api/ai/status`, retention settings, `POST /api/chat/stream` (SSE streaming from the assistant), `POST /api/voice/synthesize` (after a TTS exists).
Not adding as specified: `POST /api/tools/execute` as a public endpoint. Tools execute only inside the assistant's policy engine; exposing a direct execute endpoint would bypass confirmation and taint rules.

## 9. Technology comparisons (criteria and plan; no measured numbers yet)

| Choice | Candidates | Current lean and why | What decides it |
|---|---|---|---|
| Vector DB | pgvector, Qdrant, Weaviate, Milvus | **pgvector**: already in the schema and image, transactional filters, one datastore | filtered-ANN p95 latency and recall at your real corpus size; switch only if it misses the budget |
| Embeddings | multilingual-e5 (small/large), BGE-M3, others | keep e5-small as baseline | recall@k on a labelled Hinglish query set built from your chats; memory/latency on this CPU |
| Reranker | BGE-reranker class cross-encoders | add one | ΔMRR/nDCG over BM25+dense on the same set |
| LLM | Qwen2.5-7B-Instruct (downloading), Qwen3-8B, 3-4B class | start with Qwen2.5-7B Q4 | bake-off: tool-selection, argument accuracy, state-diff success, safety, CPU latency |
| ASR | Whisper variants via faster-whisper, distilled models | none installed | WER/CER on **your** recordings incl. Hinglish and Indian accents |
| TTS | Piper-class local engines | none installed | naturalness (human rating), latency, streaming, licence |
Hardware reality: CPU-only laptop, 15.7 GB RAM. A 7B Q4 model will answer in seconds to minutes per turn; voice conversation latency will be poor without a GPU.

## 10. Threat model (summary)

| Threat | Existing defence | Gap / action |
|---|---|---|
| Prompt / indirect injection via chat or papers | untrusted-data wrapping, taint-then-confirm, T3 refusal, id provenance, user-token authorization | validate with a real model; red-team set of hundreds |
| Cross-tenant access | project membership + 404 | **no tenant layer** (section 6); RLS tests |
| Forged webhooks | n/a (no webhook yet) | HMAC `X-Hub-Signature-256` verify, replay window, idempotency |
| SSRF / media fetch | no outbound fetch | if media download is added: allow-list Meta hosts, size/type caps, no redirects to private ranges |
| Credential leakage | secrets masked in the anonymiser, env-only secrets | add secret scanning for ingested chats (done for the labelling flow, not for stored raw text) |
| Queue poisoning / replays | job-id dedupe | idempotency keys, schema-validated payloads, DLQ review |
| Model/tool poisoning | tool registry is code, schemas strict | signed model artifacts in the registry |
| PII over-retention | encrypted uploads | retention policy + deletion of derived data (embeddings, summaries, caches) |
Residual risk that cannot be designed away: a hijacked model can still act within the signed-in user's permissions and the allowed tiers.

## 11. Roadmap mapped to the 17 phases

| Phase | State | Next concrete step |
|---|---|---|
| 1 Analysis | **done (this document)** | your review |
| 2 Architecture + schema | drafted here | decisions in section 12, then migrations |
| 3 Queue | BullMQ in place | interface hardening, `/queue/status`; RabbitMQ only if chosen |
| 4 WhatsApp ingestion | blocked for existing groups | webhook endpoint for Groups/1:1 + signature verification, if you have an Official Business Account; otherwise stop at export import |
| 5 Normalisation/storage | partial | cursor-based incremental analysis, media/reply/reaction tables |
| 6 NLP analytics | partial | Q&A analytics, sentiment (needs data), dynamic topics |
| 7 RAG + vector DB | partial | reranker model, Hinglish retrieval benchmark |
| 8 Chatbot | partial | real LLM bake-off (in progress), streaming |
| 9 Tools/control | done for the current app | extend registry per new module |
| 10 Voice | partial | install ASR, measure WER, mic UI |
| 11 Research KB | partial | real corpus, verify citations/DOIs |
| 12 Datasets | partial | **human labelling of real chats** (the biggest quality lever) |
| 13 Fine-tuning | not started | only after 12 and the baseline bake-off |
| 14 Evaluation | partial | grow golden set to hundreds |
| 15 Security hardening | partial | red-team with a real model, webhook/tenant tests |
| 16 Real-time dashboard | missing | SSE events from the job pipeline |
| 17 Production deployment | partial | add assistant, vector/queue services, health endpoints to compose |

## 12. Decisions (answers received are recorded in DECISIONS.md)

**Answered 2026-10-06:** keep BullMQ (question 2) and the product is a single-company tool, so no tenancy layer (question 3). Questions 1 and 4 remain open. Original questions:

1. **WhatsApp:** do you have (or will you get) an **Official Business Account**, and is "new business-created groups with ≤ 8 people" acceptable? If not, ingestion stays export-based.
2. **Queue:** keep BullMQ (recommended) or require RabbitMQ now?
3. **Tenancy:** is this a multi-organization SaaS (option A) or a single-company tool (option B)?
4. **Priorities:** the largest measured weakness is label quality and LLM quality, not missing features. Suggested order: finish the LLM bake-off, then human-label real chats, then Q&A analytics + sentiment, then SSE real-time, then tenancy/queue changes if chosen.
5. **Hosted models:** the master prompt allows hosted LLMs in comparisons; the repository rule so far is **self-hosted only**. Confirm it still holds.
