# Architecture decisions (ADR log)

Each entry: the decision, who made it, why, and what it rules out. Newest at the bottom. Reopen a decision only with new evidence.

## ADR-001: Keep BullMQ + Redis as the job queue (no RabbitMQ now)
- **Status:** accepted by the owner (2026-10-06).
- **Context:** the master prompt proposed RabbitMQ. The system already runs BullMQ on Redis with retries, exponential backoff, id-based de-duplication and an in-process fallback when no Redis is configured.
- **Decision:** keep BullMQ behind the `JobQueue` interface (`backend/src/queues/index.ts`). New work (webhook re-analysis, retention re-analysis) uses the same interface.
- **Consequences:** no extra stateful service to run and monitor. Python workers cannot consume the queue directly; they are called over HTTP by the Node worker (the current design). If routing/priority fan-out or direct Python consumers become necessary, add a RabbitMQ implementation of `JobQueue` (the design is in `04-queue-and-events/QUEUE_AND_EVENTS.md`); callers do not change.
- **Rules out:** running RabbitMQ and BullMQ for the same purpose; adding Kafka (replay can be rebuilt from PostgreSQL).

## ADR-002: Single-company tool, no multi-tenancy layer
- **Status:** accepted by the owner (2026-10-06).
- **Context:** isolation today is per project (role matrix + project membership, 404 for projects you cannot see).
- **Decision:** do not add `organization_id`, row-level security or per-organization settings. The product serves one company; projects are the isolation unit.
- **Consequences:** retention and deletion settings are **per project** (`Project.retentionDays`), not per organization. The WhatsApp webhook maps a conversation to a project (`WhatsappSource`), not to a tenant. If a second company ever shares the deployment, run a separate deployment or revisit this decision (a tenant layer touches every table and every query).
- **Rules out:** SaaS-style shared hosting of several unrelated companies in one database.

## ADR-003: Self-hosted models only, no external LLM/AI API
- **Status:** standing rule from the start of the project; re-confirmed implicitly by the owner's choice of a self-hosted model.
- **Decision:** the LLM (Qwen2.5-7B-Instruct Q4_K_M via llama.cpp), embeddings, reranker, ASR and TTS run on the owner's hardware.
- **Consequences:** quality and latency are bounded by this laptop (CPU only, 15.7 GB RAM). See `12-datasets-and-models`.

## ADR-004: Existing WhatsApp groups are imported by authorized export; the official API is used only where it can work
- **Status:** accepted (driven by Meta's documented limits, see `01-analysis/PHASE1_ANALYSIS_AND_GAP.md` section 3).
- **Decision:** one-time export + incremental re-import for existing groups. The Cloud API webhook (`/api/webhooks/whatsapp`) is implemented for business-created groups (max 8 participants) and 1:1 customer chats, mapped explicitly to projects.
- **Rules out:** scraping WhatsApp Web, session/cookie extraction, private-API use, database decryption.

## ADR-005: LLM proposes, deterministic code disposes
- **Decision:** the assistant never holds authority. Permission, tier, confirmation, id validation and rate limits are ordinary code; actions run with the signed-in user's own token; results are verified by reading back; the reply states what happened from executor results.
- **Details:** `07-assistant`.

## ADR-006: Derived data follows its source
- **Decision:** any purge or erasure of messages also removes what was derived from them (analysis rows, snapshots, reports, notifications, search index) or rebuilds it from what remains. Human-confirmed rows are never auto-deleted; they are counted and returned for review.
- **Details:** `09-security-and-privacy/PRIVACY_AND_RETENTION.md`.
