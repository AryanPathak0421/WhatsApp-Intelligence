# Queue and live events

## Job queue (ADR-001: BullMQ stays)

`backend/src/queues/index.ts` defines `JobQueue { enqueue, idle, close, stats, ping }` with two implementations:

| Mode | When | Behaviour |
|---|---|---|
| `bullmq` | `REDIS_URL` set | queue `wa-analysis`; `jobId` doubles as BullMQ id (enqueueing twice cannot run twice); 2 attempts, exponential backoff (5 s), keeps last 1000 completed/failed |
| `inline` | no Redis (dev/tests) | jobs run sequentially in-process, still asynchronous to the HTTP request |

Only one job type exists today: **analyze a project** (`AnalysisJob` row -> `runAnalysisJob`). Stages and progress: Queued/Starting 5, Identifying team 38,
Analyzing project 45, Indexing messages 75, Calculating progress 85, Generating report 95, Completed 100 (the former Parsing/Processing stages went with the export import). Failure messages are sanitised; a transient AI-engine outage is re-thrown so BullMQ retries.

### Debounced re-analysis (in-app chat and retention)
Jobs are created by three triggers: a message in an in-app **project group** (`services/rooms.ts`, the normal path), a retention purge that leaves messages, and the manual "Re-analyse now"
(`POST /api/projects/:id/chat/reanalyze`, direct enqueue; 409 if one is already running).
`scheduleReanalysis(projectId, queue, debounceMs)` (`services/reanalysis.ts`) coalesces bursts: each new message resets a timer (default 30 s, `ANALYSIS_DEBOUNCE_MS`, which replaced `WEBHOOK_DEBOUNCE_MS`), but a constant stream cannot postpone analysis past 5 minutes.
When the timer fires: if an analysis is already QUEUED/RUNNING the schedule retries in at least 5 s, otherwise it creates an `AnalysisJob` and enqueues it. Result: several chat messages in a row produce **one** job (tested in `rooms.test.ts`).

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
- Analysis events (`analysis.progress|completed|failed`, `notification.created`) carry ids, stage and numbers only. Published at every job stage, on completion/failure, and when notifications are created.
- Chat events carry **ids only** (`roomId`, and for typing the `actorId`), never message text, and are addressed to room members through `userIds`; when `userIds` is set only those users receive the event and no project check applies:
  `chat.message` (new message in a room), `chat.room` (room created, renamed, membership changed), `chat.typing` (ephemeral, sent to the other members only, at most once per user and room every 2 s, never stored).
- Frontend `src/lib/live.ts`: reads the stream with `fetch` (EventSource cannot send the Authorization header), refetches all queries on `analysis.completed|failed`, notifications on `notification.created`, rooms and messages on `chat.message|chat.room`; every event is re-dispatched in the page, and `pages/Chat.tsx` shows who is typing on `chat.typing`.
  After 3 consecutive failures it **falls back to polling every 30 s** and shows "Polling" in the header; on success "Live".
- Reverse proxy: disable response buffering for `/api/events` (see `11-deployment-and-ops/OPERATIONS.md`).

Tests: `backend/tests/events.test.ts` (auth required, members and admins receive progress+completion, a non-member receives nothing, no message text in payloads, stream cap) and `frontend/src/lib/lib.test.tsx` (SSE parsing).
