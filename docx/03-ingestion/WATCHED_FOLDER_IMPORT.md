# Watched-folder import (automation for a normal, personal WhatsApp)

**Why this exists:** with an ordinary WhatsApp account there is no official way for software to read a group. The only authorized source is WhatsApp's own **Export chat**. This feature removes the manual
upload step after the export, and nothing else. It reads files the owner saved into a folder; it never touches WhatsApp (no scraping, no WhatsApp Web automation, no session extraction).

## The chain
```
phone (Android): group > name > Export chat > Without media > save to Google Drive (folder named like the project)
  -> Google Drive for desktop syncs the folder to this PC            (needs the Drive app installed; not installed on this machine yet)
  -> backend watcher scans AUTO_IMPORT_DIR every 30 s                 (backend/src/services/autoimport.ts)
  -> import (same checks as the upload API) -> incremental analysis -> dashboard updates live (SSE)
```
Automatic: everything from the synced file onward. Manual (or Android-automation): the export step on the phone (Tasker/MacroDroid can repeat it on a schedule by driving WhatsApp's own Export screen; this is
fragile and is your device's UI automation, not part of this system). iPhone cannot schedule exports.

## Folder layout (`AUTO_IMPORT_DIR`)
```
<root>/README.txt
<root>/<Project name>/WhatsApp Chat with X.txt     <- drop or sync an export here (.txt or .zip)
<root>/<Project name>/imported/<yyyymmddhhmm>_<file>   <- handled files (duplicates too)
<root>/<Project name>/rejected/<...>  + <...>.reason.txt   <- not a usable chat
```
The sub-folder name must equal the project name (case-insensitive; the characters `\ / : * ? " < > | ` become `_`, trailing dots/spaces are dropped). Folders are created for you:
Settings -> "WhatsApp auto-import" -> **Create project folders** (or `POST /api/auto-import/folders`; also done at startup).

## Rules the watcher follows
1. Only **direct children** of a project folder are read; no recursion; nothing from file contents is used as a path.
2. A file is imported only after its **size and modification time were identical on two consecutive scans** and it is at least `AUTO_IMPORT_SETTLE_MS` (15 s) old, so a half-synced file is never imported.
3. `.zip`: the first `.txt` inside is extracted by a small defensive reader (no ZIP64, no encryption, directories/`__MACOSX` skipped, decompression capped at 200 MB so a zip bomb cannot exhaust memory).
4. The same checks as the upload API: must look like a WhatsApp export, an **identical file is never imported twice** (SHA-256 per project), and **a project is never analysed twice at once** (the file waits and is retried).
5. Import is **incremental**: exporting the whole chat again appends only messages that are new; the pipeline recognises old ones by deterministic ids.
6. Unknown folder name, or several projects sharing the name, is reported and the files are left untouched (rename a project or use a unique name).
7. Ignored: hidden/temp files (`.x`, `~$x`, `.tmp`, `.crdownload`, `.part`, `.gdoc`, `desktop.ini`, ...), other extensions, files over 200 MB or empty (rejected with a reason).
8. Each import is audited (`AUTO_IMPORT`, with the folder as source); the uploader of record is the project manager, else the first active admin.

## Setup
1. Install **Google Drive for desktop** on this PC and sign in with the same Google account as the phone. (This machine has no Drive folder today; OneDrive exists but is not used.)
2. Pick a Drive folder, e.g. `G:\My Drive\WhatsApp Exports`, and set `AUTO_IMPORT_DIR=G:\My Drive\WhatsApp Exports` in `private-data/dev.env` (read by `scripts/dev/dev-up.ps1`), then restart the backend.
   Without it the folder is `private-data/inbox` (local only; copy exports there by hand).
3. In the panel create the project (its name = the folder name), open Settings, press **Create project folders**.
4. In the Drive app on the phone, make sure exports are saved into that project's folder.

Production: set `AUTO_IMPORT_DIR` to a directory the backend container can read (mount the synced folder read-write: files are moved to `imported/`).

## API
`GET /api/auto-import/status` (admin): `{enabled, root, intervalMs, settleMs, lastScanAt, scans, folders[{folder, project, status ok|unknown|ambiguous, waitingFiles}], recent[{at, folder, file, outcome, detail}]}`.
`POST /api/auto-import/folders` (admin): creates missing project folders; 409 if the feature is off. Configuration: `AUTO_IMPORT_DIR`, `AUTO_IMPORT_INTERVAL_MS` (30000), `AUTO_IMPORT_SETTLE_MS` (15000).

## Limits
- Polling every 30 s (Drive sync is not instant either); events are kept in memory (last 100), the audit log is the durable record.
- Moving files into `imported/` changes the Drive folder (Drive for desktop syncs the move back to the cloud).
- A phone export includes the whole chat each time; very large chats take longer to analyse but are not re-stored message by message.
- If the export is made **with media** the zip contains pictures; only the text is read, but the zip must still be downloaded fully first.
- Not tested against a real Google Drive sync (no Drive installed here); tested with files written into a folder in the same way a sync client writes them.

## Tests
`backend/tests/autoimport.test.ts` (11): zip reader on real ZIP bytes (deflate/stored, skips junk, rejects garbage, encrypted, oversize and lying-size entries), folder creation with Windows-safe names and idempotency,
stable file imported once, duplicate and longer export (only new messages), Android-style zip, rejected files with reasons, unsupported/hidden files untouched, a growing file is not imported, waiting while an analysis runs,
unknown/ambiguous folders untouched, admin-only status.
