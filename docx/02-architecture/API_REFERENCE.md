# HTTP API reference (backend, base `/api`)

Authentication: `Authorization: Bearer <access token>` unless marked **public**. Errors: `{"error":{"code","message","details?"}}`. Validation errors are **422**, unknown or
inaccessible projects **404**, missing permission **403**, no/expired token **401**. Roles: SUPER_ADMIN, ADMIN, PROJECT_MANAGER, TEAM_MEMBER, SALES, CLIENT_VIEWER.
Older endpoints (auth, projects, chat upload, tasks, analytics, reports, overview) are described in `docs/PHASE9_BACKEND.md`; this file lists what was added or changed.

## Insights (permission `analytics:view`; project access required)

| Method and path | Purpose | Notes |
|---|---|---|
| `GET /projects/:id/qa?status=&limit=` | questions with status ANSWERED / POSSIBLY_ANSWERED / UNANSWERED, answerer, response minutes, evidence ids, plus `stats` | `POSSIBLY_ANSWERED` is never counted as answered |
| `GET /projects/:id/sentiment` | counts, per sender, per day, client sentiment, notable items with cue words | lexicon baseline, labelled as such in `method` |
| `GET /projects/:id/summaries?kind=daily\|weekly\|monthly&limit=` | hierarchical summaries, newest first, each highlight with `source_message_ids` | 422 for another `kind` |

## Status and health

| Path | Access | Returns |
|---|---|---|
| `GET /health` | public | `{status:"ok"}` (process is up) |
| `GET /ready` | public | `{status:"ready"\|"degraded"\|"not_ready", db, queue, ai}` booleans only; 503 when db or queue is down; AI down = `degraded` |
| `GET /queue/status` | `user:manage` | mode (`bullmq`/`inline`), depth by state, jobs by status, age of the oldest active job |
| `GET /ai/status` | `user:manage` | AI engine reachability and model versions (503 if unreachable) |

## Live events

`GET /events` (authenticated, `text/event-stream`). Events: `analysis.progress`, `analysis.completed`, `analysis.failed`, `notification.created`; data = `{type, projectId, jobId?, progress?, stage?, at}`.
Delivered only for projects the user can see (admins: all); max 5 simultaneous streams per user (429). No message text is ever sent.

## WhatsApp Cloud API webhook

| Method and path | Access | Behaviour |
|---|---|---|
| `GET /webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=&hub.challenge=` | **public** | echoes the challenge if the token matches `WHATSAPP_VERIFY_TOKEN`, else 403; 503 if not configured |
| `POST /webhooks/whatsapp` | **public**, HMAC-signed | requires `X-Hub-Signature-256: sha256=<hmac of the raw body with WHATSAPP_APP_SECRET>` else 401; returns `{received, stored, duplicates, unmapped, ignored}` with 200 |
| `GET /projects/:id/whatsapp-sources` | `chat:upload` | connected conversations and counters |
| `POST /projects/:id/whatsapp-sources` | `chat:upload` + project edit | body `{phoneNumberId (digits), conversationKey (group_id or wa_id), label}`; 409 if already connected (does not say where) |
| `DELETE /projects/:id/whatsapp-sources/:sid` | `chat:upload` + project edit | stops ingestion (204); stored messages stay |

## Watched-folder import (admin, `user:manage`)

`GET /auto-import/status` (folder state and recent outcomes) and `POST /auto-import/folders` (create one folder per project). See `03-ingestion/WATCHED_FOLDER_IMPORT.md`.

## Retention and erasure (per project)

| Method and path | Permission | Behaviour |
|---|---|---|
| `GET /projects/:id/retention` | `project:edit` | `{retentionDays, options:[30,90,365], min, max}` |
| `PUT /projects/:id/retention` | `project:edit` + edit access | body `{retentionDays: 30..3650 \| null}`; audited |
| `POST /projects/:id/retention/purge` | `project:edit` + edit access | purges messages older than the policy, rebuilds derived data; 400 if no policy |
| `POST /projects/:id/erase-data` | `project:delete` (admins) | body `{confirmProjectName}` must equal the project name; irreversible; audited |

## Assistant service (port 8100, proxied at `/assistant` by the dev frontend)

`POST /assistant/chat`, `POST /assistant/confirm`, `POST /assistant/cancel`, `GET /assistant/pending`, `POST /assistant/feedback`, `POST /assistant/voice`,
`GET|POST|DELETE /assistant/documents`, `GET /health`. Details in `07-assistant/ASSISTANT_IMPLEMENTATION.md`. There is deliberately **no** generic "execute tool" endpoint.

## AI engine additions (internal, token-protected when `AI_ENGINE_TOKEN` is set)

`DELETE /ai/index/{project_id}` drops a project's in-memory search index (used by purge/erase). `analyze-messages` now also returns `qa`, `sentiment` and `periodic`.
