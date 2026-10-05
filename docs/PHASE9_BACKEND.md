# Phase 9 - Node.js backend integration

Code: `backend/src/` (Express + TypeScript + Prisma). Tests: `backend/tests/` (42 integration tests, real PostgreSQL + real Redis + the real Python engine).

## Flow
```
POST /api/projects/:id/chat/upload  -> validate (ext, size, not binary, WhatsApp header) -> sha256 duplicate check
   -> AES-256-GCM encrypted file on disk (random storage key) -> ChatUpload + AnalysisJob -> queue -> 202 {jobId}
worker (BullMQ, or inline when no Redis):
   Parsing 15 -> Processing messages 30 (insert only unseen messages) -> Identifying team 38 -> Analyzing project 45
   -> Indexing 75 -> Calculating progress 85 (persist) -> Generating report 95 (notifications) -> Completed 100
GET /api/analysis/:jobId  -> status / stage / progress / sanitized error
```
Re-analysis and incremental imports always re-run the engine over ALL stored project messages, so overlapping exports only add the new messages and
tasks are never duplicated (task ids are derived from the source message id).

## Data guarantees (all covered by tests)
- `ChatMessage.originalText` is write-once; message ids are project-scoped (`<projectId>:<hash>`), so identical text in two projects never collides.
- Timestamps are stored as the WhatsApp wall-clock (no server-timezone shifts). `2026-10-01T10:00:00.000Z` means "10:00 as shown in WhatsApp".
- Re-analysis never overwrites human edits: tasks / client-pending items with `reviewState HUMAN_*` are skipped; manual role overrides (`roleSource=admin`) are
  kept and sent to the engine as overrides; manual tasks (no source message) are never deleted. Other derived tables are replaced wholesale per run.
- Human edits write `TaskHistory` + `ChangeLog` (who / when / old / new) + `AuditLog`.
- Duplicate upload -> 409 `This chat appears to have already been imported.` and nothing is created. One analysis per project at a time.
- Deleting a project cascades to all of its data and to nothing else.

## Security
- JWT access (15 min, HS256 pinned; `alg=none`, forged and expired tokens rejected) + rotating refresh tokens (hashed in DB; reuse of a spent token revokes the whole family).
- Role and active flag are read from the database on every request (demotion / deactivation is immediate). Generic login error; per-IP+email throttle (429).
- RBAC matrix in `utils/permissions.ts` + project-level membership (`ProjectMember`). Non-members get 404, not 403. CLIENT_VIEWER only receives client-facing,
  reduced payloads (no messages, evidence, contribution, risks, source ids, score components).
- Phone numbers encrypted at rest (`enc1:` AES-GCM) and masked unless the caller is admin / project manager. Uploaded chats encrypted at rest.
- Audit log: LOGIN, UPLOAD, REANALYZE, CREATE/UPDATE/DELETE project/task, CHANGE_STATUS, CHANGE_MEMBER, OVERRIDE_AI, GENERATE_REPORT, VIEW_REPORT, VIEW_SENSITIVE.
- helmet + HSTS, CORS allow-list, 1 MB JSON limit, zod validation on every body/query, no stack traces to clients, service-to-service token to the AI engine,
  secrets only from environment (startup fails naming the variable, never printing values).
- Retention: encrypted upload files are deleted after `UPLOAD_TTL_HOURS` (hourly job); messages stay in the database.

## API (all under /api, Bearer auth, cursor pagination `?limit&cursor`)
| Area | Endpoints |
|---|---|
| Auth | POST `/auth/login` `/auth/register` (first user = SUPER_ADMIN, then admin only) `/auth/refresh` `/auth/logout`, GET `/auth/me` |
| Projects | GET/POST `/projects`, GET/PUT/DELETE `/projects/:id`, GET/POST `/projects/:id/members`, DELETE `/projects/:id/members/:userId` |
| Team | GET `/projects/:id/team`, PUT `/projects/:id/team/:participantId` (role override) |
| Chat | POST `/projects/:id/chat/upload`, GET `/projects/:id/chat/uploads`, GET `/analysis/:jobId`, GET `/projects/:id/chat/analysis`, POST `/projects/:id/chat/reanalyze`, GET `/projects/:id/messages?q&sender&from&to&taskId`, GET `/projects/:id/search?q&mode` |
| Tasks | GET/POST `/projects/:id/tasks`, PUT/DELETE `/tasks/:id`, GET `/tasks/:id/evidence` (source messages + context), GET `/tasks/:id/history` |
| Analytics | GET `/projects/:id/{progress?explain=true&history=true, health, team-performance, sales, client-pending, client-response-time, velocity, risks, conflicts, timeline, insights, summary}`, PUT `/client-pending/:id` |
| Reports | POST `/projects/:id/reports/generate`, GET `/projects/:id/reports`, GET `/reports/:id?format=json\|pdf\|xlsx\|csv` |
| Misc | GET `/notifications`, POST `/notifications/:id/read`, `/notifications/read-all`, GET `/audit` (admin), GET `/health` |

## Deployment
`docker-compose.yml`: postgres (pgvector) / redis / ai-engine (internal network, no internet) / backend / worker. Only the backend is published (127.0.0.1:4000)
for a TLS-terminating reverse proxy. `npx prisma migrate deploy` runs on backend start.

## Operational requirement
The PostgreSQL database must use **UTF8** encoding (the API refuses to start otherwise): chats contain emoji and Devanagari.

## Known gaps (honest)
- **Reports ignore manual corrections**: `POST .../reports/generate` re-runs the engine; task edits are stored in the DB but not yet passed to the report. Needs an
  "overrides" input on the engine endpoint (small follow-up). Dashboard endpoints (progress/health/etc.) are computed at analysis time and also do not recompute after
  a manual task edit until the next re-analysis.
- Analysis loads all project messages in one request to the engine (fine to ~100k; chunked/streamed analysis is needed for 1M messages).
- Per-message classification (`MessageEnrichment`) is not stored; the classifier is optional (`CLASSIFIER_PATH` on the engine) and not wired into persistence yet.
- The AI project assistant (`/ai/query`) and annotation proxy are not implemented in the backend yet.
- Login throttling and caches are in-process (single node); use Redis for multi-node. No email/refresh-cookie handling (tokens are returned in JSON).
- Docker images: see the verification note in the phase summary.
