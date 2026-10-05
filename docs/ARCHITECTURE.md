# Architecture (Phase 1)

Self-hosted: **no external AI/LLM API anywhere**. Raw chat text never leaves our infrastructure.

```
React (Vite)  ->  Express API (JWT/RBAC, Prisma)  -> PostgreSQL (+pgvector)
                       |  BullMQ/Redis job
                       v
                 Node worker  ->  FastAPI ai-engine (+Celery for long stages)
                                   parse > normalise > classify > NER > tasks > resolve
                                   > temporal > commitments > client-pending > bugs
                                   > requirements > conflicts > embeddings > graph
                                   > progress > risk > health > contribution > summary
```

## 1. Folder structure

```
frontend/src/{components,pages,features,hooks,services,types,utils}
backend/src/{controllers,services,routes,middlewares,repositories,queues,workers,utils}
backend/prisma/schema.prisma
ai-engine/app/
  api/ (FastAPI + static annotation UI)   parsers/ (whatsapp.py)   annotation/
  nlp/ (normalise, hinglish, temporal)    classifiers/   ner/   tasks/ (extract, resolve, status)
  conflicts/  risks/  analytics/ (progress, health, contribution, client_response)
  knowledge_graph/  embeddings/  summarization/  evaluation/  datasets/  training/  workers/
ai-engine/data/{raw,processed,annotated,train,validation,test,synthetic}   (DVC-tracked, git-ignored)
ai-engine/models/{classifier,ner,embedding,summarizer}                      (MLflow-registered)
docs/
```

## 2. Data principles (enforced in schema + code)

1. `ChatMessage.originalText` is write-once. AI output lives in `MessageEnrichment` and derived tables.
2. Every derived row has `confidence`, `modelVersion`, `sourceMessageIds` -> every insight is traceable.
3. Human edits go to `ChangeLog` (who/when/old/new) and, for labels, `TrainingExample` (source=human_correction).
4. All rows are project-scoped; every query is filtered by `projectId` after a `ProjectMember` check.
5. Message id = hash(timestamp, sender, raw text, duplicate counter) -> re-import and incremental import are idempotent;
   `ChatUpload(projectId, sha256)` unique -> duplicate file detection.

## 3. Backend architecture (Node)

- Layers: route -> controller (zod validation) -> service -> repository (Prisma). No Prisma in controllers.
- Auth: access JWT 15m + refresh token (hashed in DB, rotated). bcrypt/argon2 password hash.
- RBAC middleware `requireRole(...)` + `requireProjectAccess(projectId, 'view'|'edit')`.
  | Role | Scope |
  |---|---|
  | SUPER_ADMIN | everything, incl. model promotion, users |
  | ADMIN | all projects in org, users, annotation |
  | PROJECT_MANAGER | own projects: upload, edit, team, reports |
  | TEAM_MEMBER | assigned tasks + project read |
  | SALES | sales + client-pending + client communication |
  | CLIENT_VIEWER | client-facing report/progress only, no raw chat, phones masked |
- Upload: multer -> temp dir, size cap, `.txt` + magic/encoding check, stream to encrypted store, sha256, dedupe,
  create `AnalysisJob`, enqueue, return `jobId` (202). Temp files purged after `UPLOAD_TTL_HOURS`.
- Worker (BullMQ): calls ai-engine stage by stage in chunks; writes results in batches; updates `AnalysisJob.stage/progress`;
  sanitized errors only. Frontend polls `GET /api/analysis/:jobId` (SSE later).
- Progress map: Uploading 5, Parsing 15, Classification 30, Task extraction 45, Requirements 55, Risk 65,
  Embeddings 75, Progress calc 85, Report 95, Complete 100.
- Audit log on upload, view-sensitive, task/status change, member change, report generation, AI override.
- Caching: Redis for analytics endpoints, invalidated when a job completes or a human edit lands.

## 4. API (Node) - summary

Auth `POST /api/auth/{login,register,refresh}` - Projects `GET/POST /api/projects`, `GET/PUT/DELETE /api/projects/:id`
Chat `POST /api/projects/:id/chat/upload` (202+jobId), `GET /api/analysis/:jobId`, `GET /api/projects/:id/messages?cursor&q&sender&category&from&to&taskId`,
`POST /api/projects/:id/chat/reanalyze`
Tasks `GET/POST /api/projects/:id/tasks`, `PUT/DELETE /api/tasks/:id`, `GET /api/tasks/:id/evidence` (source messages + context window)
Analytics `GET /api/projects/:id/{progress,progress/explain,health,team-performance,client-pending,risks,timeline,conflicts,analytics}`
Team `GET/PUT /api/projects/:id/team/:participantId` (role override) - Notifications `/api/notifications`
Reports `POST /api/projects/:id/reports/generate`, `GET /api/projects/:id/reports`, `GET /api/reports/:id?format=pdf|xlsx|csv|json`
AI `POST /api/projects/:id/ai/query` (retrieval + structured answers, local only), semantic search `GET /api/projects/:id/search?q=`
Annotation (ADMIN) `/api/annotation/*` proxies ai-engine. All list endpoints paginated (cursor).

## 5. Python ai-engine - endpoints

`/ai/parse /classify /ner /tasks /task-resolution /requirements /commitments /client-pending /conflicts /bugs /risks /progress
/contribution /summarize /search /embeddings /timeline /insights` (+ `/ai/annotation*`, `/health`).
Internal network only, shared service token. Stateless: input = message ids + text (+ prior state for incremental), output = JSON with
`confidence, source_message_ids, model_version`. Phase 2 implements `/ai/parse` and `/ai/annotation*`.

## 6. NLP pipeline (per message, then per project)

Original text (kept) -> language ID (en/hi/hinglish) -> unicode normalise -> Hinglish normalisation
(dictionary + transliteration + abbreviation/spelling; never overwrite original) -> context window (prev N / next N)
-> rules + classifier ensemble (rules for high-precision patterns; TF-IDF/LR baseline -> fine-tuned multilingual transformer)
-> NER (spaCy baseline -> transformer) + `dateparser` for deadlines (stores original text, normalised ts, tz, confidence)
-> task candidates -> **task resolution** -> status engine -> project-level engines.

Model lifecycle: candidate -> evaluated on project-held-out test -> manual promotion (never automatic) -> versioned in `ModelVersion`.

## 7. Algorithms (deterministic, explainable, weights configurable)

**Task resolution.** Candidate task = message with TASK/assignment intent. Follow-up message m joins task T if
`score = 0.35*cos(emb(m),emb(T)) + 0.25*entity_overlap + 0.15*person_overlap + 0.15*module_match + 0.10*time_decay >= tau`
(time_decay = exp(-dt/7d)); also uses the context window ("Done" after "Payment API?"). Best-T wins; margin < 0.08 -> mark ambiguous/NEEDS_REVIEW.
Incremental import re-attaches new messages to existing tasks, never duplicates.

**Status (evidence-based).** Each linked message contributes a signed evidence signal
(completion +, progress ~, blocked -, client-pending dependency, test-pass +, deploy +, reopen/bug -), weighted by confidence and recency.
Completed requires strong evidence (completion verb with the task as subject, or test+deploy chain); a single ambiguous word ("done")
without referent stays IN_PROGRESS/NEEDS_REVIEW. Stored in `Task.statusEvidence`.

**Progress.** `overall = sum(w_i * c_i) / sum(w_i) * 100`, `c_i` = 1 completed, 0.5-0.9 in testing/deployed-not-approved (configurable), 0 else, cancelled excluded.
`w_i` from weight model: keyword/module priors (UI 1, API 3, payment 5, architecture 8) refined by learned story-point regressor; manual override wins.
Sub-progress (development/design/testing/deployment/client approval/documentation) = same formula over `Task.domain`.
`progress/explain` returns each task's contribution + the open items holding the percentage back.

**Health (0-100).** `sum_k w_k * s_k` with s_k in [0,1]: progress vs time elapsed, deadline adherence, risk, blocked ratio,
client-dependency (open age-weighted), bug load, velocity trend. Default weights 0.20/0.15/0.15/0.10/0.15/0.10/0.15. Status: >=80 HEALTHY, 60-79 AT_RISK, 40-59 CRITICAL, <40 BLOCKED.
Components stored in `ProjectHealth.components`.

**Developer contribution (0-100).** `0.35*weighted_completion + 0.20*on_time_rate + 0.15*bug_fix_score + 0.10*deployment_score
+ 0.10*commitment_fulfilment + 0.10*(1 - blocked_share_penalty)`, normalised by assigned workload so heavy load is not punished
and message count is excluded. Returns the breakdown for every developer.

**Client pending.** Triggers: waiting/pending/credentials/approval/UAT patterns (EN + Hinglish) + classifier CLIENT_PENDING + task `externalDependency`.
Item opens with `waitingSince = request message time`. Auto-resolves when a later client message (response-paired by thread/entity/time)
carries approval/provided-info intent; resolution message stored. Impact = f(task weight, blocking downstream tasks, age).
Response time = pairing team request -> first matching client reply (avg/median/min/max).

**Risk score (0-100).** `sum_f w_f * s_f` over deadline proximity, overdue duration, blocked duration, client inactivity,
requirement churn, unresolved bugs, dependency count, communication drop, backlog. LOW <30, MEDIUM <55, HIGH <75, CRITICAL >=75.
Each risk keeps its `factors` JSON + source messages + recommended action.

**Conflicts.** Pair statements on the same topic (embedding sim > t, entity match, same module, time-ordered), run NLI/contradiction
classifier + polarity heuristics (approved vs not approved, completed vs unavailable). Always emitted as "potential contradiction - needs verification".

## 8. Frontend architecture

Pages: Login, ExecutiveDashboard, Projects, ProjectDashboard (health + "Why N%?" drawer), ChatAnalysis/Explorer (message + category + entities +
confidence + evidence), Tasks (board/table, edit), Team (+ developer detail), ClientPending, Sales, Risks, Timeline, Conflicts, Reports, Analytics,
Annotation (admin), ModelRegistry (admin), Settings. Cross-cutting: TanStack Query (cache keys per project), Axios interceptor (refresh),
route guards by role, `EvidenceDrawer` reused everywhere an AI result appears, `ConfidenceBadge` (Needs Review < 0.70), `StatusBadge`, skeleton/empty/error states.

## 9. Phases (status)

1 Architecture+DB (this doc, `schema.prisma` validated) - done. 2 Parser + annotation + synthetic data - done.
3 Baseline ML -> needs real labelled chats for honest metrics. 4-12 per plan.
