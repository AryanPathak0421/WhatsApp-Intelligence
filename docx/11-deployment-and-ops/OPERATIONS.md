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
| Embedded PostgreSQL | 15433 | dev only; databases `wa_intel_dev`, `wa_intel_test`; migrations applied by `scripts/dev/embedded-pg/start.mjs`, no pgvector (embedding column is TEXT) |

Dev login and generated secrets are in `private-data/` (git-ignored). Background-process note: processes started by an assistant tool call may be killed after about 30 minutes; `dev-up.ps1` uses `Start-Process`, which is independent.

## Configuration (environment variables)
| Variable | Used by | Meaning |
|---|---|---|
| `DATABASE_URL`, `JWT_ACCESS_SECRET`, `JWT_REFRESH_SECRET`, `FIELD_ENCRYPTION_KEY` (64 hex) | backend | required |
| `REDIS_URL` | backend | enables BullMQ and cross-process live events; absent = inline queue |
| `AI_ENGINE_URL`, `AI_ENGINE_TOKEN` | backend | engine address and shared service token |
| `CORS_ORIGIN`, `TRUST_PROXY`, `UPLOAD_DIR`, `UPLOAD_TTL_HOURS`, `MAX_UPLOAD_BYTES` | backend | |
| `AUTO_IMPORT_DIR`, `AUTO_IMPORT_INTERVAL_MS`, `AUTO_IMPORT_SETTLE_MS` | backend | watched folder for exported chats (dev default `private-data/inbox`); see `03-ingestion/WATCHED_FOLDER_IMPORT.md` |
| `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN`, `WEBHOOK_DEBOUNCE_MS` | backend | webhook disabled unless both secrets are set; debounce default 30000 |
| `BACKEND_URL`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_TIMEOUT_S`, `ASSISTANT_*`, `PENDING_TTL_S`, `RAG_ABSTAIN_BELOW`, `TAINT_REQUIRES_CONFIRMATION` | assistant | see `assistant/wa_assistant/config.py` |
| `EMBED_MODEL`, `CLASSIFIER_PATH`, `MODEL_REGISTRY_DIR`, `PREDICTION_LOG`, `ANNOTATION_*` | AI engine | |

## Health checks
`GET /api/health` (liveness), `GET /api/ready` (db + queue + AI; booleans only), admin-only `GET /api/queue/status` and `GET /api/ai/status`, assistant `GET /health`.
Orchestrators should use `/api/ready` for readiness (503 = do not route traffic). `degraded` = AI engine down: the app serves stored data but cannot analyse.

## Production (docker-compose)
`docker-compose.yml`: postgres (pgvector), redis, backend, worker, edge nginx (TLS), internal no-internet network; backup and restore scripts (restore tested); see `docs/DEPLOYMENT.md`.
**Not yet in compose:** the assistant service, the llama.cpp server, the AI-engine model volume for the LLM. **nginx config changes (SSE and webhook locations) are unvalidated here: no nginx binary on this machine; run `nginx -t` before deploying.**
The reverse proxy must not buffer `/api/events`; the webhook location passes the body untouched.

## Runbooks
- **Analysis stuck:** `GET /api/queue/status` (oldest active job age); inline mode runs jobs in the API process, so restarting the API fails running jobs (re-run with the reanalyze endpoint).
- **Live updates show "Polling":** the stream cannot stay open (proxy buffering, network); data still refreshes every 30 s.
- **Webhook returns 401:** wrong `WHATSAPP_APP_SECRET`, or a proxy altered the body. **200 but nothing stored:** the conversation is not mapped (`unmapped` in the response).
- **Assistant says the model is not reachable:** start `llama-server` (dev-up) or point `LLM_BASE_URL` at your model server.
- **Prisma generate fails with EPERM:** a running backend holds the query engine DLL; stop the backend first.
- **Backend tests:** need a database; embedded: run `scripts/dev/embedded-pg/start.mjs`, then `TEST_DATABASE_URL=postgresql://wa:wa_dev_pw@localhost:15433/wa_intel_test TEST_SKIP_MIGRATE=1 npx vitest run`.
- **Secrets that appeared in the HG chat (website password, SMS API key) must be rotated**; the original group chat still contains them.
