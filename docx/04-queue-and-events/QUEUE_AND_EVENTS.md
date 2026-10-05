# Queue and live events

## Job queue (ADR-001: BullMQ stays)

`backend/src/queues/index.ts` defines `JobQueue { enqueue, idle, close, stats, ping }` with two implementations:

| Mode | When | Behaviour |
|---|---|---|
| `bullmq` | `REDIS_URL` set | queue `wa-analysis`; `jobId` doubles as BullMQ id (enqueueing twice cannot run twice); 2 attempts, exponential backoff (5 s), keeps last 1000 completed/failed |
| `inline` | no Redis (dev/tests) | jobs run sequentially in-process, still asynchronous to the HTTP request |

Only one job type exists today: **analyze a project** (`AnalysisJob` row -> `runAnalysisJob`). Stages and progress: Parsing 15, Processing messages 30, Identifying team 38,
Analyzing 45, Indexing 75, Calculating progress 85, Generating report 95, Completed 100. Failure messages are sanitised; a transient AI-engine outage is re-thrown so BullMQ retries.

### Debounced re-analysis (webhook and retention)
`scheduleReanalysis(projectId, queue, debounceMs)` coalesces bursts: each new message resets a timer (default 30 s, `WEBHOOK_DEBOUNCE_MS`), but a constant stream cannot postpone analysis past 5 minutes.
When the timer fires: if an analysis is already QUEUED/RUNNING the schedule retries in at least 5 s, otherwise it creates an `AnalysisJob` and enqueues it. Result: three webhooks in a row produce **one** job (tested).

### Not implemented (by decision)
RabbitMQ/Kafka, per-stage queues (`ai.embedding`, `ai.summarization`, ...), a dead-letter queue as a separate queue (BullMQ keeps failed jobs for inspection), cursor-based incremental analysis
(analysis re-reads the whole project because task status and Q&A depend on full history; this is fast enough at current sizes and is simpler to keep correct). If any becomes necessary the
`JobQueue` interface is the seam; a RabbitMQ implementation would use a topic exchange with TTL retry queues and a consumer-side idempotency table keyed by message id.

## Live events (Server-Sent Events)

```
analysis worker / API --events.publish--> bus --(in-process emitter | Redis channel wa:events)--> every API process --> SSE streams (authorized per event)
```
- `backend/src/events/bus.ts`: single-process emitter; with `REDIS_URL` events go over Redis so a separate worker process reaches the API process holding the browser connections. At-most-once, best effort.
- `backend/src/controllers/events.ts`: `GET /api/events`; authenticates the bearer token, checks project visibility when an event is **delivered** (membership cached 30 s), heartbeat every 25 s,
  `X-Accel-Buffering: no`, max 5 streams per user.
- Events carry ids, stage and numbers only. Published at every job stage, on completion/failure, and when notifications are created.
- Frontend `src/lib/live.ts`: reads the stream with `fetch` (EventSource cannot send the Authorization header), refetches all queries on `analysis.completed|failed`, notifications on `notification.created`.
  After 3 consecutive failures it **falls back to polling every 30 s** and shows "Polling" in the header; on success "Live".
- Reverse proxy: disable response buffering for `/api/events` (see `11-deployment-and-ops/OPERATIONS.md`).

Tests: `backend/tests/events.test.ts` (auth required, members and admins receive progress+completion, a non-member receives nothing, no message text in payloads, stream cap) and `frontend/src/lib/lib.test.tsx` (SSE parsing).
