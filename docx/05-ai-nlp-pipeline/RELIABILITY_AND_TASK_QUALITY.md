# Reliability of the headline numbers, and task-title quality

## Why this exists
Progress % and the health score are arithmetic over the **tasks** the analysis extracted. On a real chat ("Get Right Home", 434 messages, Aug to Oct 2026) the engine found only **9 tasks**, all
low-confidence and all waiting for review, and several were chat fragments ("I URL", "I sub URL for", "Join sir"). The dashboard still showed a bold **78% / Critical**. The arithmetic was exact; its
input was not. Two changes address that.

## 1. Reliability level (backend, computed on read)
Code: `backend/src/services/reliability.ts`. It never changes a number; it states how far the numbers can be trusted, and the UI says so.

| Level | Condition (first match wins; reasons are returned in plain language) |
|---|---|
| `INSUFFICIENT` | not analysed yet, or fewer than 3 tasks |
| `LOW` | at least 70% of tasks still `NEEDS_REVIEW`, or average task confidence < 0.65, or (>= 100 messages and < 3 tasks per 100 messages) |
| `MEDIUM` | 30-70% of tasks need review, or average confidence < 0.8, or (>= 100 messages and < 5 tasks per 100) |
| `HIGH` | none of the above |

- It is computed from the stored tasks each time, so **a person confirming or correcting tasks raises the level immediately**, with no re-analysis.
- `GET /api/projects/:id/overview` now returns `reliability {level, reasons, tasks, needsReview, messages}`; client viewers get the level only (no reasons or counts).
- `GET /api/executive`: each project row has `reliability`; `totals.atRisk` and `totals.critical` count only **trusted** (HIGH/MEDIUM) projects, `totals.averageProgress` averages only trusted
  projects, and `totals.lowConfidence` says how many projects were left out.
- UI: project dashboard shows an amber banner with the reasons and a "Review tasks" button, replaces the Critical/At risk badge with **Low confidence**, and dims the percentage; the executive table shows
  **Low confidence** instead of a health status, and the "At risk / critical" card states how many projects were not counted.
- Thresholds are judgment calls, not fitted to data; change them in `assess()` (covered by `backend/tests/reliability.test.ts`, 8 tests).

## 2. Task-title quality gate (AI engine)
Code: `ai-engine/app/intelligence/title_quality.py`, applied at all three task-creation points in `tasks.py` (volunteered, self-announced, assigned).
A title is accepted only if, after removing placeholders (`<url>`, `<Media omitted>`), links, WhatsApp mentions (`@` + U+2068..U+2069), invisible direction marks, greetings/vocatives ("sir", "madam"),
people's names and English/Hinglish function words, **at least two content words remain**, it is not a short "I ..." / "we ..." remark (<= 4 words), and it does not end on a dangling connector
("for", "and", ...). Two-letter all-caps acronyms (UI, DB, QA) count as content. Rejected messages simply do not become tasks (they can still act as evidence for existing ones).
Tests: `ai-engine/tests/test_title_quality.py` (28).

### Measured effect
| | Before | After |
|---|---|---|
| "Get Right Home" tasks | 9 (incl. "I URL", "I sub URL for", "Join sir" x3) | **4** |
| Progress / health shown | 78% / 49.7 Critical | 100% (4 of 4 tasks "completed") / 49.3, **labelled Low confidence** |
| Reliability | not assessed | **LOW**: 4 of 4 tasks need review; avg confidence 60%; 4 tasks in 434 messages |
| Unseen-chat benchmark (`bench/unseen_eval`) | recall 100% / 80% / 33% | unchanged (100% / 80% / 33%): no real task was lost |

**Read the table honestly:** removing junk made the percentage look *more* confident (100%), which is exactly why the reliability label matters. The remaining four tasks are also weak (for example
"me your best idea"); the true problem is **recall**: 4 tasks from 434 messages means most real work was not extracted. The gate removes false tasks; it does not find missing ones.

## What would actually fix recall
Human labels of real tasks from this chat (50-100 messages) to measure precision/recall and to tune the extractors; then, if the rules cannot reach the target, a trained span/intent model on those labels.
Until then the right behaviour for a project like this one is what the UI now does: show the numbers, but say they are a rough guide.
