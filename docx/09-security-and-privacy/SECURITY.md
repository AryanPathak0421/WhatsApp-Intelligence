# Security: threat model and implemented controls

Scope: single-company deployment (ADR-002). Legend: **Implemented and tested**, **Implemented, not exercised in production conditions**, **Gap**.

| Threat | Control | State |
|---|---|---|
| Unauthenticated access | JWT access tokens (15 min), rotating single-use refresh tokens, bcrypt; every router authenticates | Implemented and tested |
| Privilege escalation | permission matrix (6 roles) + project membership enforced in the backend; non-members get 404 | Implemented and tested |
| Assistant acts beyond the user | it executes only with the user's own token; tiers T0-T3; T2 needs a UI button; ids must come from earlier lookups; rate limit | Implemented and tested (sandbox + real backend smoke) |
| Prompt injection (direct/indirect via chats, task titles, documents) | untrusted-data wrapping, taint-then-confirm, T3 refusal, schema validation, no tool can send data out | Tested against a **worst-case obedient stub** (11 attack cases incl. delete, role change, payment, export, cross-project, create user, add member): 0 state changes. **Not yet tested with the real model** (bake-off running) |
| Forged webhook | HMAC-SHA256 over the raw body, constant-time compare; unsigned/tampered/wrong-secret rejected, nothing stored | Implemented and tested |
| Webhook replay / duplicates | idempotent per WhatsApp message id | Implemented and tested. No timestamp-window check (an old but valid signed event is accepted once) |
| Unauthorised data via webhook | conversations must be explicitly mapped to a project by an editor; unmapped dropped | Implemented and tested |
| Cross-project data leakage | per-project index/queries; SSE delivery checks project access per event; document scope proven with the backend | Implemented and tested |
| Live-event leakage | payloads carry ids/stages only; non-members receive nothing | Implemented and tested |
| Credential leakage | secrets only in env; anonymiser masks pasted passwords/keys for labelling; field encryption AES-256-GCM for uploads and phones; no query strings or bodies in request logs | Implemented and tested. Stored raw chat text is not secret-scanned |
| SSRF / media fetch | the system makes no outbound fetch of user-supplied URLs; media not downloaded | No exposure today; allow-list required before adding media download |
| Mass assignment / injection (SQL) | zod validation on bodies and queries; Prisma parameterised queries | Implemented and tested |
| DoS | nginx rate limits (login, upload, API, webhook), body size caps, per-user SSE cap, assistant message and write rate limits | Implemented; nginx config **not validated** (no nginx on this machine) |
| Model/tool poisoning | tool registry is code; model files are not auto-updated | Gap: no signature check for model artifacts |
| Over-retention of personal data | per-project retention, purge, erasure with derived data | Implemented and tested (see PRIVACY_AND_RETENTION) |
| Audit | backend `AuditLog` (who/what/when), assistant `audit.jsonl` (decisions, results, no message text) | Implemented |

## Residual risks (cannot be designed away)
- A hijacked model can still do what the signed-in user is allowed to do within tiers and rate limits.
- The lexicon/rule extractors can misread chats; derived data is advisory and carries evidence and review flags.
- Development tokens in `private-data/` are for local use only.

## Operational requirements before exposing to the internet
Set real secrets (`scripts/gen-secrets.sh`), HTTPS via the edge proxy, `TRUST_PROXY`, restrict CORS, set `WHATSAPP_APP_SECRET`/`WHATSAPP_VERIFY_TOKEN` only if using the webhook, run the backup/restore routine,
rotate any credential that ever appeared in a chat (the HG chat contained a website password and an SMS API key: **rotate them**).
