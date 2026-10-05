# WhatsApp Project Intelligence & Management System

Turns exported WhatsApp project chats into structured project intelligence (tasks, status, client pending, requirements, risks, progress, health,
contribution, timeline, reports). **All AI runs on your own servers; no external LLM/AI API is used.** Every insight links back to the original messages.

```
frontend/ (React)  ->  backend/ (Express, Prisma, PostgreSQL, BullMQ)  ->  ai-engine/ (FastAPI, rules + ML + local embeddings)
```

## Run locally (dev)
```bash
# 1. infrastructure (dev only)
docker run -d --name wa_intel_pg -e POSTGRES_USER=wa -e POSTGRES_PASSWORD=wa_dev_pw -e POSTGRES_DB=wa_intel -p 15432:5432 pgvector/pgvector:pg16
docker run -d --name wa_intel_redis -p 56379:6379 redis:7-alpine      # optional: without it the backend runs jobs in-process

# 2. AI engine  (Python 3.11/3.12 recommended)
cd ai-engine && python -m venv .venv && .venv/Scripts/python -m pip install -r requirements-dev.txt torch
EMBED_MODEL=hashing AI_ENGINE_TOKEN=dev-token .venv/Scripts/python -m uvicorn app.api.main:app --port 18001

# 3. backend  (copy .env.example values; see docs/PHASE9_BACKEND.md)
cd backend && npm ci && npx prisma migrate deploy && npx tsx src/index.ts

# 4. frontend
cd frontend && npm ci && npm run dev
```
The first registered user becomes SUPER_ADMIN. Tests: `ai-engine: pytest` · `backend: npx vitest run` (needs the two containers) · `frontend: npx vitest run`.

## Production (docker compose)
```bash
scripts/gen-secrets.sh && docker compose --profile setup run --rm model-fetch && docker compose up -d --build
```
Edge nginx (TLS) is the only exposed service; database, Redis and the AI engine sit on a network with no internet access. Backups: `docker compose --profile backup up -d`. Full guide, hardening checklist and what still needs verifying on first deploy: `docs/DEPLOYMENT.md`.

## Documentation (docs/)
`ARCHITECTURE.md` (design + algorithms) · `DATASET_STRATEGY.md` · `PHASE3_BASELINE_RESULTS.md` · `PHASE4_BENCHMARK.md` · `PHASE5_INTELLIGENCE.md` ·
`PHASE6_ANALYTICS.md` · `PHASE7_SEARCH_GRAPH.md` · `PHASE8_SUMMARIZATION_REPORTS.md` · `PHASE9_BACKEND.md` · `PHASE10_FRONTEND.md` · `PHASE11_TESTING_BENCHMARKS.md` ·
**`DEPLOYMENT.md`** (production) · `MODEL_LIFECYCLE.md` · `LABELING_PLAN.md` (next step: real data)

## Honest status
Built and tested (~190 automated tests): parser, annotation tool, training harness, task/status/client-pending/requirement/conflict/risk engines, progress/health/contribution, semantic search + knowledge graph,
summaries + reports (PDF/Excel/CSV/JSON), secure backend with RBAC and async jobs, React dashboard. Engine handles ~100k messages in ~2 min (CPU); 1M messages is not supported yet.

**Accuracy on real data is unknown.** Rule-based extraction scored 100% on its own synthetic chats but only ~44% task recall / ~31% correct final status on hand-written chats it had not seen
(`docs/PHASE11_TESTING_BENCHMARKS.md`). Label real project chats (annotation tool at `/annotate`) and train/evaluate on them before trusting any number. Health/risk weights are uncalibrated defaults.
Each phase doc ends with its limits.
