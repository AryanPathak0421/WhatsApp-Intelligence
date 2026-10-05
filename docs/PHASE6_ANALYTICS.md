# Phase 6 - Progress, health, contribution

Code: `ai-engine/app/analytics/{progress,health,contribution}.py`, wired into `analyze()` / `POST /ai/analyze`
(new keys: `progress`, `health`, `velocity`, `progress_timeline`, `contribution`, `sales`, `communication`).

## Progress
`overall = sum(weight x credit) / sum(weight) x 100`, cancelled tasks excluded. Default credit is STRICT (only COMPLETED = 1);
partial credit for IN_PROGRESS is configurable (`progress_credits`) because it is an assumption, not evidence.
Sub-progress: development / design / documentation by task domain; testing = tested completed dev weight / dev weight (+ testing tasks);
deployment = weight with deploy evidence / total; client approval = resolved approval/UAT/feedback items / all such items.
`null` = no evidence for that area (never shown as 0). `explanation` powers "Why N%?": per-task points and share, the open tasks holding progress back,
status counts, reliability (share of tasks not flagged for review) and warnings (default weights, completed-but-needs-review, no tasks).
Also: daily progress timeline (+/- delta per day) and weekly velocity with trend.

## Health (0-100)
Seven components (progress vs elapsed time, deadline adherence, risk, blocked share, client dependency, bug load, velocity), weights configurable
(`health_weights`, defaults 0.20/0.15/0.15/0.10/0.15/0.10/0.15). Components without data are dropped and the weights renormalised; they are listed
in `unavailable`. Status: 80+ HEALTHY, 60-79 AT_RISK, 40-59 CRITICAL, <40 BLOCKED; forced BLOCKED only if every open task is blocked.
A project with a delivery date is judged against elapsed time; without one, absolute progress is used (stated in the reason).

## Contribution (0-100, explainable)
`0.35 weighted completion + 0.20 on-time + 0.15 bug fixes + 0.10 deployments + 0.10 commitments`, missing components renormalised, then
multiplied by `(1 - 0.10 x blocked share)` (a penalty, never credit - blocks are often external). Bug fixes / deployments are relative to the team max.
Message count is returned as `info_only` and is proven by test not to affect the score. `low_sample` is set below 3 tasks.
Also: sales activity (follow-ups, pending/resolved, payment discussions, proposals, escalations) and communication stats.

## Tests / validation
17 analytics tests (weighted-not-counted, 60% example, cancelled exclusion, sub-progress, timeline, velocity, thresholds, renormalisation,
timeline-aware health, blocked override, configurable weights, message-count independence, penalty-only blocked, explainability sums).
Crash/range sweep over 120 synthetic projects: all outputs JSON-serialisable, progress and health within 0-100.

## Not validated (important)
- Weights and thresholds are design defaults, NOT calibrated against human judgement. On synthetic chats (many blocked / client-pending items by
  construction) health lands mostly CRITICAL/AT_RISK - that says nothing about real projects. Calibrate by having managers rate 15-30 real projects
  and fitting/validating weights, then compare predicted vs reviewed progress (planned in the evaluation spec).
- Task weights come from keyword priors (UI 1-2, API 3, payment/deploy/admin 5, "architecture/major" 8), not a learned story-point model yet.
- Progress is only as good as task extraction/status (Phase 5 limits apply); check `reliability` and `warnings`.
