# Privacy, retention and erasure

Per-project (ADR-002: no organization-level settings). Code: `backend/src/services/retention.ts`, `backend/src/controllers/retention.ts`.

## What is stored
In-app chat messages (`RoomMessage`, plain text; project-group messages also mirrored into `ChatMessage`), raw messages (`ChatMessage.originalText`, never modified; includes messages kept from the former
WhatsApp import), participants (names; **phone numbers**, present only for previously imported senders, **encrypted** with AES-256-GCM), pending chat invitations (e-mail address, optional name, SHA-256 of the token),
derived analysis rows, analysis snapshots (JSON), reports, notifications, the AI engine's in-memory search index, assistant audit/feedback files (no message text).
Direct messages are stored only in `RoomMessage`, are never mirrored or analysed, and cannot be read by admins through the API.
No uploaded chat files are accepted any more (WhatsApp ingestion removed, ADR-007); the former hourly purge of encrypted uploads is gone with it. Files left in `UPLOAD_DIR` by the former import are deleted when the project is erased.

## Retention policy
`Project.retentionDays` (null = keep). Allowed 30 to 3650 (UI options 30 / 90 / 365). Set with `PUT /api/projects/:id/retention` (needs `project:edit` and edit access; audited).
A sweep runs every 6 hours in the API process (`runRetentionSweep`) and on demand with `POST /api/projects/:id/retention/purge`.

### What a purge does
1. Deletes messages with `timestamp < now - retentionDays` (their enrichments and embeddings cascade), and the project's in-app group messages (`RoomMessage`) older than the cutoff.
2. If messages remain: keeps only the newest analysis snapshot per kind (older ones contain text from deleted messages), deletes reports and notifications older than the cutoff, drops the engine's search index, and schedules a
   re-analysis so derived rows (tasks, decisions, ...) are rebuilt from what remains. **Tested:** a task that came only from deleted messages is gone after re-analysis.
3. If no messages remain: wipes all derived data of the project.
4. **Human-confirmed rows are not auto-deleted** (a person decided to keep them): the response lists `humanEditedItemsRetained` so someone can review them.
5. Audit log entries are kept (they record that a purge happened).

## Erasure
`POST /api/projects/:id/erase-data` with `{"confirmProjectName": "<exact name>"}`; needs `project:delete` (admins). Irreversible. Removes messages (including the project's in-app group messages), all derived rows, snapshots, reports, notifications, analysis jobs,
participants, upload rows from the former import and their encrypted files in `UPLOAD_DIR` (the in-app chat's empty carrier upload is kept), drops the search index. Keeps the project shell, members and the audit log (including the erase record).
Tested: wrong name 400, missing name 422, project managers 403, full erase leaves 0 rows in every message/derived table.

## Gaps
- No PII detection/masking at ingest (the anonymiser exists for the labelling workflow only).
- Retention uses message timestamps in the project's wall clock treated as UTC (the same convention everywhere), so the cutoff can be off by the timezone offset (hours).
- Database backups (`scripts/backup.sh`) keep deleted data until the backup itself ages out; apply the same retention to backups.
- Assistant audit and feedback files are not covered by project retention (they contain no message text but do contain tool arguments such as task titles you asked it to create).
- Embeddings in production live in `MessageEmbedding` (pgvector) and are deleted by cascade; this was tested on the embedded dev database where that column is TEXT.
