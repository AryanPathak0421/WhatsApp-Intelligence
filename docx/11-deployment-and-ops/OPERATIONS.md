# Operations: running, configuring and checking the system

## Development stack (this laptop, no Docker)
```powershell
powershell -ExecutionPolicy Bypass -File scripts/dev/dev-up.ps1            # start everything installed (detached; logs in private-data/logs)
powershell -ExecutionPolicy Bypass -File scripts/dev/dev-up.ps1 -NoLlm     # without the language-model server
powershell -ExecutionPolicy Bypass -File scripts/dev/dev-down.ps1          # stop by port (never kills unrelated processes)
```
| Service | Port | Notes |
|---|---|---|
| Frontend (Vite) | 5199 | 5173 belongs to another app on this machine |
| Backend | 4000 | queue mode `inline` without Redis |
| AI engine / annotation tool | 8000 | `http://localhost:8000/annotate` |
| Assistant | 8100 | `/health` reports LLM reachability |
| LLM (llama.cpp, Qwen2.5-7B Q4_K_M) | 8081 | OpenAI-compatible `/v1`; CPU, about 1-4 tokens/s |
| Embedded PostgreSQL | 15433 | dev only; databases `wa_intel_dev`, `wa_intel_test`; migrations applied by `scripts/dev/embedded-pg/start.mjs` at server start; to apply new migrations to the **running** server use `cd scripts/dev/embedded-pg && node migrate.mjs` (both databases); no pgvector (embedding column is TEXT) |

Dev login and generated secrets are in `private-data/` (git-ignored). Background-process note: processes started by an assistant tool call may be killed after about 30 minutes; `dev-up.ps1` uses `Start-Process`, which is independent.

## Configuration (environment variables)
| Variable | Used by | Meaning |
|---|---|---|
| `DATABASE_URL`, `JWT_ACCESS_SECRET`, `JWT_REFRESH_SECRET`, `FIELD_ENCRYPTION_KEY` (64 hex) | backend | required |
| `REDIS_URL` | backend | enables BullMQ and cross-process live events; absent = inline queue |
| `AI_ENGINE_URL`, `AI_ENGINE_TOKEN` | backend | engine address and shared service token |
| `CORS_ORIGIN`, `TRUST_PROXY` | backend | |
| `ANALYSIS_DEBOUNCE_MS` | backend | quiet period after the last project-group message before analysis runs (default 30000; capped at 5 minutes for a constant stream). Replaced `WEBHOOK_DEBOUNCE_MS` |
| `SMTP_HOST`, `SMTP_PORT` (465), `SMTP_SECURE` (true), `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM` | backend | outgoing e-mail for chat invitations and member notices; nothing is sent without `SMTP_HOST`. Keep `SMTP_PASS` only in the environment; see `03-ingestion/IN_APP_CHAT.md` |
| `INVITE_TTL_DAYS` | backend | invitation link lifetime (default 7) |
| `FRONTEND_URL` | backend | base of links in e-mails (default `http://localhost:5199`); in production the public HTTPS address |
| `UPLOAD_DIR` | backend | only so erasing a project can delete files left by the former chat-export import |
| `BACKEND_URL`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_TIMEOUT_S`, `ASSISTANT_*`, `PENDING_TTL_S`, `RAG_ABSTAIN_BELOW`, `TAINT_REQUIRES_CONFIRMATION` | assistant | see `assistant/wa_assistant/config.py` |
| `EMBED_MODEL`, `CLASSIFIER_PATH`, `MODEL_REGISTRY_DIR`, `PREDICTION_LOG`, `ANNOTATION_*` | AI engine | |

## Health checks
`GET /api/health` (liveness), `GET /api/ready` (db + queue + AI; booleans only), admin-only `GET /api/queue/status` and `GET /api/ai/status`, assistant `GET /health`.
Orchestrators should use `/api/ready` for readiness (503 = do not route traffic). `degraded` = AI engine down: the app serves stored data but cannot analyse.

## Production (docker-compose)
`docker-compose.yml`: postgres (pgvector), redis, AI engine, backend, worker, edge nginx (TLS); backup and restore scripts (restore tested); see `docs/DEPLOYMENT.md`.
Networks: `internal` (no internet) for Postgres, Redis, the AI engine and the backend; `edge` for the proxy; `egress` (outbound only) attached to the **backend alone** so invitation e-mails reach the SMTP server.
Removing `egress` from the backend disables e-mail delivery but nothing else (invitations are still created, `emailSent: false`).
**Not yet in compose:** the assistant service, the llama.cpp server, the AI-engine model volume for the LLM. **nginx config changes are unvalidated here: no nginx binary on this machine; run `nginx -t` before deploying.**
The reverse proxy must not buffer `/api/events`. The former webhook and upload locations and their rate-limit zones were removed with WhatsApp ingestion (ADR-007).

## Runbooks
- **Analysis stuck:** `GET /api/queue/status` (oldest active job age); inline mode runs jobs in the API process, so restarting the API fails running jobs (re-run with the reanalyze endpoint).
- **Live updates show "Polling":** the stream cannot stay open (proxy buffering, network); data still refreshes every 30 s.
- **Project shows no analysis:** messages reach a project only through its in-app project group; analysis starts `ANALYSIS_DEBOUNCE_MS` after the last message. "Re-analyse now" answers 400 when the project has no messages.
- **Invitation e-mails not arriving:** `SMTP_HOST` unset (response `emailSent: false`), wrong app password (backend log shows the send failure, without body or token), or in docker the backend is not on the `egress` network. Links pointing at localhost mean `FRONTEND_URL` is not set to the public address.
- **Assistant says the model is not reachable:** start `llama-server` (dev-up) or point `LLM_BASE_URL` at your model server.
- **Prisma generate fails with EPERM:** a running backend holds the query engine DLL; stop the backend first.
- **Backend tests:** need a database; embedded: run `scripts/dev/embedded-pg/start.mjs`, then `TEST_DATABASE_URL=postgresql://wa:wa_dev_pw@localhost:15433/wa_intel_test TEST_SKIP_MIGRATE=1 npx vitest run`.
- **Secrets that appeared in the HG chat (website password, SMS API key) must be rotated**; the original group chat still contains them.
