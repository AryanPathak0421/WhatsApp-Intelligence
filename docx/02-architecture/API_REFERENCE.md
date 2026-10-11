# HTTP API reference (backend, base `/api`)

Authentication: `Authorization: Bearer <access token>` unless marked **public**. Errors: `{"error":{"code","message","details?"}}`. Validation errors are **422**, unknown or
inaccessible projects **404**, missing permission **403**, no/expired token **401**. Roles: SUPER_ADMIN, ADMIN, PROJECT_MANAGER, TEAM_MEMBER, SALES, CLIENT_VIEWER.
Older endpoints (auth, projects, tasks, analytics, reports, overview) are described in `docs/PHASE9_BACKEND.md`; this file lists what was added or changed.
That document also describes the chat-export upload, which **no longer exists** (removed 2026-10-11 with all WhatsApp ingestion, ADR-007).

## Chat analysis (project access required)

| Method and path | Access | Behaviour |
|---|---|---|
| `GET /projects/:id/chat/analysis` | project view | latest analysis job and its state |
| `POST /projects/:id/chat/reanalyze` | `chat:upload` + project edit | "Re-analyse now" on the Chat analysis page; 202 `{jobId}`; 400 if the project has no messages; 409 if an analysis is already running |
| `GET /analysis/:jobId` | project view | one analysis job |
| `GET /projects/:id/messages`, `GET /projects/:id/search` | project view + `chat:view_raw` | message explorer and search over stored messages |

Messages reach a project only through its in-app project group (below); analysis then runs automatically after `ANALYSIS_DEBOUNCE_MS`.

## Insights (permission `analytics:view`; project access required)

| Method and path | Purpose | Notes |
|---|---|---|
| `GET /projects/:id/qa?status=&limit=` | questions with status ANSWERED / POSSIBLY_ANSWERED / UNANSWERED, answerer, response minutes, evidence ids, plus `stats` | `POSSIBLY_ANSWERED` is never counted as answered |
| `GET /projects/:id/sentiment` | counts, per sender, per day, client sentiment, notable items with cue words | lexicon baseline, labelled as such in `method` |
| `GET /projects/:id/summaries?kind=daily\|weekly\|monthly&limit=` | hierarchical summaries, newest first, each highlight with `source_message_ids` | 422 for another `kind` |

## Reliability of project numbers

`GET /projects/:id/overview` adds `reliability {level: HIGH|MEDIUM|LOW|INSUFFICIENT, reasons[], tasks, needsReview, messages}` (client viewers: level only). `GET /executive` rows add `reliability`; `totals` adds `lowConfidence` and excludes LOW/INSUFFICIENT projects from `atRisk`, `critical` and `averageProgress`. See `05-ai-nlp-pipeline/RELIABILITY_AND_TASK_QUALITY.md`.

## Status and health

| Path | Access | Returns |
|---|---|---|
| `GET /health` | public | `{status:"ok"}` (process is up) |
| `GET /ready` | public | `{status:"ready"\|"degraded"\|"not_ready", db, queue, ai}` booleans only; 503 when db or queue is down; AI down = `degraded` |
| `GET /queue/status` | `user:manage` | mode (`bullmq`/`inline`), depth by state, jobs by status, age of the oldest active job |
| `GET /ai/status` | `user:manage` | AI engine reachability and model versions (503 if unreachable) |

## Live events

`GET /events` (authenticated, `text/event-stream`). Analysis events: `analysis.progress`, `analysis.completed`, `analysis.failed`, `notification.created`; data = `{type, projectId, jobId?, progress?, stage?, at}`,
delivered only for projects the user can see (admins: all). Chat events: `chat.message`, `chat.room`, `chat.typing`; data = `{type, projectId, roomId, actorId?, at}`, delivered only to the room members listed in
the event's `userIds`. Max 5 simultaneous streams per user (429). No message text is ever sent.

## In-app chat (signed-in; a room that is not yours answers 404)

Details, permissions and privacy rules: `03-ingestion/IN_APP_CHAT.md`.

| Method and path | Access | Behaviour |
|---|---|---|
| `GET /rooms`, `POST /rooms`, `POST /rooms/direct` | signed-in; create needs `member:manage` (+ project edit for a project group) | my rooms with last message and unread count; create a group; one direct room per pair (201 new, 200 existing) |
| `GET /rooms/:id`, `PATCH /rooms/:id` | room member; rename: creator/admin | details with members; rename |
| `GET /rooms/:id/messages?before&limit`, `POST /rooms/:id/messages` | room member | oldest-first page with `hasMore`; send `{text<=4000, replyToId?}`, 60 per minute per user; project-group messages are mirrored into `ChatMessage` and analysed |
| `POST /rooms/:id/typing` | room member | ephemeral typing indicator (never stored): a `chat.typing` event to the **other** members only, at most one broadcast per user and room every 2 s; 204 |
| `POST /rooms/:id/read` | room member | marks read (drives unread counts) |
| `POST /rooms/:id/members`, `DELETE /rooms/:id/members/:uid` | creator/admin adds or removes; anyone can leave | membership; a project group needs project access |
| `GET /room-users?projectId=` | signed-in | who the caller may add / message (empty for client accounts) |
| `POST /rooms/:id/invite` | group creator/admin with project edit; 30 per hour | `{email, name?}`: an existing account is added at once (200, notice e-mail); otherwise a single-use invitation link is e-mailed (201, `emailSent`) |
| `GET /rooms/:id/invites`, `DELETE /rooms/:id/invites/:iid` | group creator/admin | pending invitations; revoke one (204) |
| `GET /invites/:token` | **public** | inviter, group, project, expiry, `accountExists`; 404 invalid or revoked, 410 already used or expired |
| `POST /invites/:token/accept` | **public**, rate-limited | `{name, password (>=10)}`: creates a `CLIENT_VIEWER` account with view access to the project and group membership, returns tokens (201); 409 if an account with that e-mail exists |

## Retention and erasure (per project)

| Method and path | Permission | Behaviour |
|---|---|---|
| `GET /projects/:id/retention` | `project:edit` | `{retentionDays, options:[30,90,365], min, max}` |
| `PUT /projects/:id/retention` | `project:edit` + edit access | body `{retentionDays: 30..3650 \| null}`; audited |
| `POST /projects/:id/retention/purge` | `project:edit` + edit access | purges messages older than the policy, rebuilds derived data; 400 if no policy |
| `POST /projects/:id/erase-data` | `project:delete` (admins) | body `{confirmProjectName}` must equal the project name; irreversible; audited |

## Removed (2026-10-11, ADR-007)

`GET/POST /webhooks/whatsapp`, `/projects/:id/whatsapp-sources`, `POST /projects/:id/chat/upload`, `GET /projects/:id/chat/uploads`, `/auto-import/*`, `/google/*`. These paths now answer 404.

## Assistant service (port 8100, proxied at `/assistant` by the dev frontend)

`POST /assistant/chat`, `POST /assistant/confirm`, `POST /assistant/cancel`, `GET /assistant/pending`, `POST /assistant/feedback`, `POST /assistant/voice`,
`GET|POST|DELETE /assistant/documents`, `GET /health`. Details in `07-assistant/ASSISTANT_IMPLEMENTATION.md`. There is deliberately **no** generic "execute tool" endpoint.

## AI engine additions (internal, token-protected when `AI_ENGINE_TOKEN` is set)

`DELETE /ai/index/{project_id}` drops a project's in-memory search index (used by purge/erase). `analyze-messages` now also returns `qa`, `sentiment` and `periodic`.
`POST /ai/parse` was removed (the backend no longer parses exports). The WhatsApp-format parser and the .txt file endpoints that remain in the engine are offline evaluation/annotation tooling for the benchmark datasets; the product never calls them.
