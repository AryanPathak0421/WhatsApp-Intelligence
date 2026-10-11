# Security: threat model and implemented controls

Scope: single-company deployment (ADR-002). Legend: **Implemented and tested**, **Implemented, not exercised in production conditions**, **Gap**.
Since 2026-10-11 there is no WhatsApp webhook, no chat-file upload and no Google Drive OAuth (ADR-007), so their public endpoints, secrets and stored OAuth tokens no longer exist.

| Threat | Control | State |
|---|---|---|
| Unauthenticated access | JWT access tokens (15 min), rotating single-use refresh tokens, bcrypt; every router authenticates (exceptions: health/ready and the two invitation routes below) | Implemented and tested |
| Privilege escalation | permission matrix (6 roles) + project membership enforced in the backend; non-members get 404 | Implemented and tested |
| Assistant acts beyond the user | it executes only with the user's own token; tiers T0-T3; T2 needs a UI button; ids must come from earlier lookups; rate limit | Implemented and tested (sandbox + real backend smoke) |
| Prompt injection (direct/indirect via chat messages, task titles, documents) | untrusted-data wrapping, taint-then-confirm, T3 refusal, schema validation, no tool can send data out | Tested against a **worst-case obedient stub** (11 attack cases incl. delete, role change, payment, export, cross-project, create user, add member): 0 state changes. Real model: 0 safety violations in the 37-case bake-off (see `10-evaluation`) |
| Chat access | a room that is not yours answers 404; direct messages readable only by the two members (admins included in "no"); project groups require project access and disappear for anyone who loses it; client accounts cannot start DMs or groups | Implemented and tested (`rooms.test.ts`) |
| Invitation link guessing or reuse | token = 48 random bytes (base64url); only its SHA-256 is stored; single use (claimed atomically, so two simultaneous accepts cannot both succeed); expires after `INVITE_TTL_DAYS` (7); a newer invitation to the same address revokes the older; managers can revoke; the public accept route is rate-limited per IP (20 per 15 min) and never creates an account for an existing e-mail | Implemented and tested (`invites.test.ts`) |
| Invitation abuse (spam, privilege) | only the group's creator or an admin with project edit access can invite; 30 invitations per hour per person; an accepted invitation grants only `CLIENT_VIEWER` with **view** access to that one project | Implemented and tested |
| E-mail content injection / leakage | user-provided names are escaped in e-mails; no e-mail address in the audit log; send failures logged without body or token | Implemented |
| Cross-project data leakage | per-project index/queries; SSE delivery checks project access per analysis event; document scope proven with the backend | Implemented and tested |
| Live-event leakage | payloads carry ids/stages only; analysis events reach only users who can see the project; chat events reach only the room members listed in `userIds` | Implemented and tested |
| Credential leakage | secrets only in env (incl. `SMTP_PASS`); anonymiser masks pasted passwords/keys for labelling; field encryption AES-256-GCM for phone numbers (from earlier imports); no query strings or bodies in request logs | Implemented and tested. Stored raw chat text is not secret-scanned |
| Data exfiltration from the host | Postgres, Redis and the AI engine sit on the `internal` docker network with no internet access. **Exception:** the backend is also on the `egress` network (outbound only) so invitation e-mails reach the SMTP server; nothing else joins it | Implemented in `docker-compose.yml`; not exercised in production. The backend could in principle reach any outbound host; restrict egress to the SMTP host with a firewall if that matters |
| SSRF / media fetch | the system makes no outbound fetch of user-supplied URLs; the only outbound connection is SMTP to the configured server | No exposure today; allow-list required before adding media download |
| Mass assignment / injection (SQL) | zod validation on bodies and queries; Prisma parameterised queries | Implemented and tested |
| DoS | nginx rate limits (login/refresh, API, SSE), 1 MB body cap, per-user SSE cap, chat send limit (60/min), invitation limits, assistant message and write rate limits | Implemented; nginx config **not validated** (no nginx on this machine) |
| Model/tool poisoning | tool registry is code; model files are not auto-updated | Gap: no signature check for model artifacts |
| Over-retention of personal data | per-project retention, purge, erasure with derived data (incl. in-app group messages) | Implemented and tested (see PRIVACY_AND_RETENTION) |
| Audit | backend `AuditLog` (who/what/when, incl. chat invitations and member changes), assistant `audit.jsonl` (decisions, results, no message text) | Implemented |

## Residual risks (cannot be designed away)
- A hijacked model can still do what the signed-in user is allowed to do within tiers and rate limits.
- The lexicon/rule extractors can misread chats; derived data is advisory and carries evidence and review flags.
- Invitation links travel by e-mail; anyone who obtains an unused link before it expires can accept it (scope is limited to view access on one project).
- In-app messages are stored in plain text (database-level encryption at rest only); there is no end-to-end encryption.
- Development tokens in `private-data/` are for local use only.

## Operational requirements before exposing to the internet
Set real secrets (`scripts/gen-secrets.sh`), HTTPS via the edge proxy, `TRUST_PROXY`, restrict CORS, set `FRONTEND_URL` to the public HTTPS address (it is the base of invitation links), configure SMTP with an app password or a transactional mail service kept only in the environment,
run the backup/restore routine, rotate any credential that ever appeared in a chat (the HG chat, an exported WhatsApp chat used as evaluation data, contained a website password and an SMS API key: **rotate them**).
