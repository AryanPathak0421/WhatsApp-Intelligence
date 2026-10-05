# WhatsApp ingestion

Two authorized paths exist. Neither bypasses WhatsApp security (no scraping, no session extraction, no private APIs, no database decryption).

## Path A: exported chat (existing groups)

The only authorized way to get an **existing** group. Upload the `.txt` export (the backend validates extension, binary content, size, and that it looks like a WhatsApp export).
Messages get deterministic ids (`<projectId>:<hash>`), so re-uploading a longer export of the same chat appends only the new messages (incremental import); the user does not
have to start over. Details: `docs/PHASE9_BACKEND.md`, `docs/PHASE4_BENCHMARK.md`.

**Automating Path A for a normal personal WhatsApp:** see [WATCHED_FOLDER_IMPORT](WATCHED_FOLDER_IMPORT.md) (phone export to Google Drive, synced folder, automatic import).

## Path B: Cloud API webhook (business-created groups and 1:1 chats)

### What Meta allows (verified against Meta documentation, Oct 2026)
- Groups API groups are **created by the business**, invite-only, **max 8 participants**, need an **Official Business Account**, unavailable for WhatsApp Business-app numbers.
- Existing consumer groups cannot be read; group messages are **not** part of history sync (coexistence syncs only 1:1 chats, last 6 months).
- Group media webhooks do not include media asset ids in history sync; this system records media as metadata only and downloads nothing.
- Reactions / replies for inbound **group** webhooks: support is **unverified**. Replies (`context.id`) are stored when present; reactions are ignored (counted, not stored).
Sources and the full capability matrix: `01-analysis/PHASE1_ANALYSIS_AND_GAP.md` section 3. Re-check Meta's docs before relying on this; they change.

### Flow
```
Meta -> POST /api/webhooks/whatsapp (raw body)
  1 verify HMAC-SHA256 (X-Hub-Signature-256) over the RAW bytes with WHATSAPP_APP_SECRET   -> 401 if invalid, nothing stored
  2 normalise Cloud API payload -> UnifiedMessage[] (text, media metadata, reply, reaction; statuses skipped)
  3 look up an active WhatsappSource for (phone_number_id, group_id or sender wa_id)        -> unmapped: dropped and counted, never stored
  4 per project, serialised: find/create participant (phone stored encrypted), insert ChatMessage (id = <projectId>:wa_<sha1(message id)>, skipDuplicates)
  5 schedule ONE debounced analysis per project (default 30 s, max wait 5 min; never two concurrent analyses of a project)
  6 respond 200 {received, stored, duplicates, unmapped, ignored} so Meta does not retry
```

### Unified message
`messageId, source:"whatsapp", phoneNumberId, conversationId (group_id or wa_id), isGroup, senderId, senderName, timestamp (UTC), messageType (text|image|audio|video|document|sticker|reaction|unsupported), text, replyTo, media{kind,mimeType,caption}, reaction{...}`.
Stored mapping: `ChatMessage.originalText = text = body` (media: `<Media omitted>` + caption, same convention as exports), `messageType MEDIA` for media, `replyToId` resolved to the stored id,
`timestamp` converted to wall-clock-as-UTC in the project timezone (default Asia/Kolkata) so webhook and export messages sort together.

### Idempotency and ordering
Meta redelivers; the same WhatsApp message id always maps to the same row id, so a retry stores nothing (`duplicates` in the response). `seq` is assigned per project under an in-process lock
(one API process). Out-of-order delivery is fine: analysis sorts by timestamp.

### Setup runbook
1. Set `WHATSAPP_APP_SECRET` (the Meta app secret, 16+ chars) and `WHATSAPP_VERIFY_TOKEN` (a random string you choose, 8+ chars) in the backend environment. Without them the webhook answers 503.
2. In Meta's app dashboard set the callback URL to `https://<your host>/api/webhooks/whatsapp` and the same verify token; subscribe to `messages`.
3. In the panel (or via API) connect each conversation: `POST /api/projects/:id/whatsapp-sources {phoneNumberId, conversationKey, label}`. Until you do, everything from that conversation is dropped.
4. Check `GET /api/projects/:id/whatsapp-sources` for `lastEventAt` and `messageCount`.

### Not done / limits
- **Never run against Meta's real servers** (no credentials here); tested with correctly signed fixtures shaped like Cloud API payloads.
- Reactions, media download, message edits/deletes, status webhooks: not stored.
- The debounce timers live in the API process; a restart loses pending timers until the next message arrives (no data loss, only a delayed analysis).
- Mapping one conversation to two projects is refused (409).

### Tests
`backend/tests/whatsapp.test.ts` (9): normalisation, wall-clock conversion, verification handshake, missing/wrong/tampered signatures store nothing, permission matrix for source management,
idempotent storage with unmapped/ignored counts and encrypted phone, one debounced analysis for a burst, disconnect stops storing.
