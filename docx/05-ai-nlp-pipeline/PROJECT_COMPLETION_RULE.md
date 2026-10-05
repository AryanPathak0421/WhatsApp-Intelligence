# Project-level completion rule

Code: `ai-engine/app/intelligence/completion.py`, hooked into `pipeline.analyze` right after task building (`result["project_completion"]`).

## Problem it fixes
Task linking works per task; a delivery announcement ("project is live and deployed", "project is completed") names the project, not each task. Open tasks stayed TODO and, on the real HG
chat, the dashboard reported a delivered project as **22% complete / CRITICAL health** with a task shown as overdue.

## Rule
1. Find the **latest** message by a **non-client** sender matching *subject (project / website / app / portal / everything / ...) within 30 characters of a completion word (completed, delivered,
   live and deployed, went live, ho gaya, ...)*.
2. Ignore conditionals and negations: once / when / after / if / until / will be / soon / not / nahi / yet / pending.
3. If a **client** message after it contains a bug report, rejection or complaint, the state is `DISPUTED` and **nothing is closed**. Otherwise `CLAIMED`.
4. On `CLAIMED`, close tasks that are TODO or IN_PROGRESS and were created before the announcement. BLOCKED and CANCELLED are left alone.
5. Every task closed this way gets `needs_review = true`, an evidence entry (`project_completion`, weight 0.6), a status-trace event `project_completed`, confidence capped at 0.6 and the review
   reason "closed by the project-completion announcement, not by evidence about this task; verify".
Result object: `{message_id, ts, sender, text, state, closed_task_ids[]}` (or `disputed_by_message_id`).

## Effect on the real chat (HG, anonymised)
Progress 22.2% -> 100%, health 46.4 CRITICAL -> 79.1 AT_RISK, risk MEDIUM -> LOW, all three extracted tasks COMPLETED (two flagged for review).

## Limits
Verified on one real chat plus 4 unit tests (`ai-engine/tests/test_completion.py`: announcement phrases, closes open tasks and flags them for review, client pushback disputes it, a client saying "complete" is not a delivery claim). One announcement closes everything older, so a chat with a premature "done" message can over-close; those tasks stay flagged for review.
Client-pending items and bugs are not closed by this rule.
