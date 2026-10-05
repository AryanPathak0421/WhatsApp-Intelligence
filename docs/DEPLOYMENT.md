# Production deployment

Status of this document: configuration and scripts were written and statically validated (compose file, shell syntax, backup/restore round trip against a real PostgreSQL).
**The full container stack has not been brought up end to end** - Docker Desktop on the development machine crashed during the AI-engine image build (the backend image did build).
Section 10 lists exactly what to verify on first deploy.

## 1. Topology
```
Internet -> [edge: nginx, TLS, rate limits, SPA]  -- internal network (no internet) -->  backend (API) ---> postgres (pgvector)
                                                                                            |---------> redis
                                                                                            '---------> ai-engine (self-hosted NLP, offline)
                                                                    worker (BullMQ, same image as backend) -> ai-engine, postgres
```
Only `edge` publishes ports (80/443). Postgres, Redis, the AI engine, the backend and the worker sit on a Docker network with `internal: true`, i.e. **no outbound internet**: even a
compromised container cannot send chat data out. The only moment internet is needed is the one-off model download (`model-fetch`, public weights only).

## 2. Requirements
| | Minimum (pilot, <= 50k messages/project) | Recommended |
|---|---|---|
| CPU / RAM | 4 vCPU / 12 GB | 8 vCPU / 24 GB |
| Disk | 30 GB SSD | 100 GB SSD + separate backup target |
| GPU | not required | optional NVIDIA (set `DEVICE=cuda`, add the `deploy.resources` block in compose) |
| Software | Docker Engine 26+ with Compose v2, a DNS name, a TLS certificate | |
Measured (CPU only): a 100k-message chat analyses in ~2 min and peaks ~1.1 GB in the AI engine (`docs/PHASE11_TESTING_BENCHMARKS.md`). 1M-message projects are not supported yet.

## 3. First deployment
```bash
git clone <repo> && cd WhatsApp-Group_analysis
scripts/gen-secrets.sh                      # writes .env (chmod 600); edit PUBLIC_URL
# TLS certificate -> deploy/certs/fullchain.pem and deploy/certs/privkey.pem  (see section 4)
docker compose --profile setup run --rm model-fetch     # one-off, needs internet: downloads public model weights into the `models` volume
docker compose up -d --build
docker compose ps                           # wait until postgres, redis, ai-engine, backend are "healthy"
```
Create the first account (it becomes SUPER_ADMIN; afterwards only admins can create users):
```bash
curl -sk https://YOUR_HOST/api/auth/register -H 'content-type: application/json' \
  -d '{"email":"you@company.com","name":"Your Name","password":"a-long-passphrase"}'
```
Then sign in at `https://YOUR_HOST`, create users and projects, add members to projects, upload a chat.
Database migrations run automatically on backend start (`prisma migrate deploy`). The Postgres cluster is created with UTF8; the API refuses to start otherwise.

## 4. TLS
Option A - existing certificate: copy `fullchain.pem` and `privkey.pem` into `deploy/certs/` (mounted read-only into `edge`).
Option B - Let's Encrypt with certbot (webroot is already wired: port 80 serves `/.well-known/acme-challenge/` from the `certbot-www` volume):
```bash
docker compose up -d edge                    # needs a (temporary self-signed) cert in deploy/certs so nginx can start; port 80 must be reachable from the internet
docker compose --profile certbot run --rm certbot certonly --webroot -w /var/www/certbot -d intel.example.com
scripts/renew-certs.sh intel.example.com     # copies the issued cert into deploy/certs and restarts edge; run it from cron weekly (it renews only when due)
```
nginx terminates TLS 1.2/1.3, sets HSTS, CSP (`default-src 'self'` - the UI loads nothing from third parties), X-Frame-Options DENY, no-referrer, and rate-limits login (10/min/IP), uploads (6/min/IP) and the API (20 req/s/IP).
Syntax check without restarting: `docker compose run --rm --no-deps edge nginx -t`.

## 5. Secrets and configuration
| Variable | Purpose | If lost / leaked |
|---|---|---|
| `FIELD_ENCRYPTION_KEY` | AES-256-GCM key for uploaded chats and phone numbers | **Lost: that data is unrecoverable.** Keep a copy in a password manager, separate from backups. Rotation is not automated (re-encrypt = re-upload). |
| `JWT_ACCESS_SECRET`, `JWT_REFRESH_SECRET` | token signing / refresh | Leaked: rotate and restart; every user is logged out. |
| `AI_ENGINE_TOKEN` | backend <-> AI engine | Leaked: rotate in `.env`, `docker compose up -d`. |
| `POSTGRES_PASSWORD`, `REDIS_PASSWORD` | datastores (not exposed outside Docker) | Rotate and recreate the containers. |
Compose refuses to start when a required secret is missing (`${VAR:?...}`), and the backend refuses to start on weak/missing secrets. Nothing secret is ever in the frontend bundle.

## 6. Operations
**Health**: `docker compose ps` (all have healthchecks); backend `GET /health` (DB reachable) from inside the network; AI engine `GET /health`, `GET /ai/model` (serving versions).
**Logs**: `docker compose logs -f backend worker ai-engine edge`. The backend and nginx write one JSON line per request (method, path with ids masked, status, ms, user id, request id) and **never** query strings, headers or bodies.
Rotation is configured (20 MB x 5 per container). Forward them to your log stack if you have one. Audit trail (who uploaded / viewed sensitive data / changed a task / generated a report) is in the `AuditLog` table, readable by admins at `GET /api/audit`.
**Scaling**: `docker compose up -d --scale worker=3` for parallel analysis jobs (one job per project at a time is enforced). The AI engine keeps its search index in memory per process: run a single replica unless you add sticky routing (the backend re-indexes automatically after a restart).
**Upgrades**: `git pull && docker compose build && docker compose up -d` (migrations run on start). Take a backup first. Roll back = previous image tag + restore if a migration was destructive (none so far).
**Retention**: encrypted upload files are deleted after `UPLOAD_TTL_HOURS` (messages and analysis stay). Deleting a project (admin only) cascades to all its data. There is no "delete my data across all projects" tool.

## 7. Backup and restore (tested: `scripts/test-backup-restore.sh`)
```bash
docker compose --profile backup up -d        # nightly 02:30: pg_dump (custom format) + tar of the encrypted uploads volume + sha256 manifest, 14-day retention, into ./backups
scripts/backup.sh                            # or run by hand (needs the PG* env vars)
# restore (stop writers first):
docker compose stop backend worker
docker compose run --rm -v "$PWD/backups:/backups:ro" -e PGHOST=postgres -e PGUSER=wa -e PGPASSWORD=$POSTGRES_PASSWORD -e PGDATABASE=wa_intel \
  --entrypoint bash backup /scripts/restore.sh /backups/db-<stamp>.dump /backups/uploads-<stamp>.tar.gz
docker compose up -d
```
The round-trip test proves: rows including Devanagari/emoji and upload files come back byte-for-byte, re-restoring over existing data replaces it, a corrupted dump is refused by checksum before anything is touched, and retention only prunes old files.
Also back up: `.env` (especially `FIELD_ENCRYPTION_KEY`) **separately**, and the `models` volume or at least the model registry (`registry.json`) if you trained models. Copy `./backups` off the host (the host disk is not a backup). **Do a restore drill on a scratch machine before go-live and quarterly.**

## 8. Security hardening checklist
- [ ] TLS in place, HTTP redirects, HSTS preloaded only after you are sure (it is long-lived).
- [ ] `.env` is mode 600, not in git; secrets generated by `gen-secrets.sh`; `FIELD_ENCRYPTION_KEY` backed up off-host.
- [ ] Host firewall allows only 80/443 (+ SSH from your IPs). Postgres/Redis/AI ports are not published (verify: `docker compose ps`, `ss -ltnp`).
- [ ] Docker engine and base images patched; rebuild monthly (`docker compose build --pull`).
- [ ] Disk encryption on the host (LUKS/BitLocker/cloud volume encryption): application-level encryption covers uploads and phone numbers, **message text in PostgreSQL is not encrypted at the application level** - protect it with disk encryption and restricted DB access.
- [ ] Users: SUPER_ADMIN count minimal; CLIENT_VIEWER accounts only for people who may see progress; project membership reviewed (Settings -> Project access).
- [ ] Phone numbers: only admins/project managers see them unmasked (audited as VIEW_SENSITIVE).
- [ ] Backups copied off-host, restore drill done, retention set per your policy.
- [ ] `npm audit` / `pip-audit` reviewed (known: Prisma CLI dev-tool chain, pip/setuptools tooling - see Phase 11 doc).
- [ ] Browser: refresh token lives in localStorage (XSS-exposed). The CSP (`script-src 'self'`) is the mitigation; moving to an httpOnly cookie flow is the better long-term design (not built).
- [ ] Privacy/legal: WhatsApp chats contain personal data of third parties (names, phone numbers, client details). Make sure you have a lawful basis, a retention period and an access policy before importing real chats.

## 9. Troubleshooting
| Symptom | Likely cause / fix |
|---|---|
| `backend` exits: "Database encoding is ... must be UTF8" | Postgres was created non-UTF8; recreate the DB with `ENCODING 'UTF8'` (compose does this by default for new volumes). |
| `backend` exits: "Invalid configuration: JWT_ACCESS_SECRET ..." | missing/short secret in `.env`; names the variable, never its value. |
| Job FAILED "Analysis service is unavailable" | AI engine unhealthy: `docker compose logs ai-engine`; first start loads models (up to ~40 s). Retry by re-uploading (the failed upload does not block it). |
| Job FAILED "Analysis failed" | AI engine rejected the service token (`AI_ENGINE_TOKEN` mismatch) or crashed; check engine logs. |
| Upload returns 409 "already imported" | identical file already in this project - by design. Upload the newer export instead. |
| Upload 413 | file over 200 MB (`MAX_UPLOAD_BYTES`) or over nginx's 210 MB. |
| 429 on login | rate limit (nginx 10/min/IP and the app's 8 failures/15 min per IP+email). |
| Everyone suddenly logged out | JWT secrets changed, or clocks skewed between host and clients. |
| Restored data but uploads/phones unreadable | `FIELD_ENCRYPTION_KEY` differs from the one used when the data was written. |
| Search slow after AI-engine restart | the in-memory index rebuilds lazily from the database on first search. |

## 10. First-deploy verification (not done on the dev machine)
1. `scripts/check-compose.sh`, then `docker compose build` - **the ai-engine image build (torch CPU wheel) has never completed on the dev machine**.
2. `docker compose run --rm --no-deps edge nginx -t` (nginx config never executed by nginx).
3. Healthy containers; register the first admin; upload `ai-engine/eval/unseen/a_shop_redesign.txt` as a smoke test; confirm job -> COMPLETED, tasks visible, evidence drawer works.
4. `docker network inspect` shows `internal: true`; from inside `ai-engine`: `python -c "import urllib.request; urllib.request.urlopen('https://example.com', timeout=3)"` must FAIL.
5. Backup + restore drill (section 7). 6. Re-run the CI workflow (`.github/workflows/ci.yml`, also never executed on GitHub).
