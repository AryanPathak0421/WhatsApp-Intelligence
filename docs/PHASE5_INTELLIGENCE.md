# Phase 5 - Task / requirement / client-pending / conflict / risk intelligence

Code: `ai-engine/app/intelligence/` (rules-first, evidence-based, no external AI). Endpoint: `POST /ai/analyze`.
Optional classifier (`CLASSIFIER_PATH`) adds category votes; the engines work without it.

| Module | What it does |
|---|---|
| `temporal.py` | EN/Hinglish deadlines (Friday, kal tak, EOD, 5 PM, 15th Nov, in 3 days) resolved against the MESSAGE time; keeps original text + confidence |
| `tasks.py` | assignment detection (vocative / mention / unknown name -> review), title, priority, weight, domain; multi-message linking (topic overlap + assignee + recency + context); evidence-based status machine with `status_trace` |
| `client_pending.py` | open/resolved dependency items (credentials, approval, UAT, payment, content...), age, impact, auto-resolution by later client message; client response-time pairing (avg/median/min/max) + inactivity days |
| `requirements.py` | requirement versions per key (e.g. payment-provider: stripe -> razorpay), changed-by, impact |
| `conflicts.py` | opposing claims on same topic by different authors -> "Potential contradiction", always NEEDS_VERIFICATION |
| `bugs_commitments.py` | bug lifecycle OPEN -> INVESTIGATING -> IN_PROGRESS -> FIXED -> CLOSED / REOPENED; promises with deadline + fulfilled/missed |
| `risks.py` | 8 weighted factors -> 0-100 score + per-risk records (severity, recommended action, source messages); factor contributions sum to the score |

Design rules enforced by tests: ambiguous "Done" never completes a task (needs review); "ready ... but credentials nahi mile" -> BLOCKED with
dependency; a client requirement is not a task; progress message mentioning "production" does not complete a deploy task; normal progress
(not ready -> completed) is not a conflict; every derived object has source message ids + model version.

## Evaluation (`python -m app.evaluation.eval_intelligence`)
Measured on 120 SYNTHETIC projects (template data written by the same developer as the rules, so this is regression/coverage, **not accuracy**):
task detection F1 0.997, assignee 1.00, deadline 1.00, final status 0.88, completed-false-positive 1.1%, client pending F1 0.996,
explicit requirement change F1 1.00, bug detection F1 1.00.
The status 0.88 is mostly gold noise ("haven't started yet" after "working on"), a few real linking misses remain.
Unit tests: hand-written scenario chat (`tests/scenario_chat.py`) with expected facts, 26 intelligence tests.

## Known limits (be honest)
- Rules are tuned to English/Hinglish phrasing I could think of; real chats will break them. Needs the real labelled set (same schema) via `--gold`.
- Task linking uses lexical/alias overlap, not embeddings yet (Phase 7). Paraphrases without shared words will not link.
- Roles for people who never speak are unknown; unknown assignees are flagged for review.
- Conflict detection covers two dimensions (state, approval) only.
- No relative-date handling for non-English weekdays beyond a few Hindi names; ambiguous "kal" gets lower confidence.
