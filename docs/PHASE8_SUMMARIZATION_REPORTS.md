# Phase 8 - Local summarization and reports (no external LLM)

Code: `app/summarization/{extractive,executive}.py`, `app/reports/{builder,export}.py`, `app/evaluation/rouge.py`.
API: `POST /ai/summarize`, `POST /ai/report?format=json|pdf|xlsx|csv`.

## Approach: levels 1-2 only, by design
1. **Executive summary = evidence-bound templates.** Every sentence is rendered from a fact computed from the analysis result
   (progress, health, pending items, overdue, blockers, requirement changes, conflicts, top risk, top next action) and carries the task / message ids that
   justify it. `verify_summary()` re-checks each number and id against the result; tampering is caught (tested). Nothing is "generated" so nothing can be hallucinated;
   the cost is repetitive wording.
2. **Key messages = extractive** (TextRank centrality over embeddings + work-signal prior + MMR with near-duplicate removal). Selected messages are quoted verbatim
   with sender / time / id, filtered by period for daily and weekly digests.
3. **Abstractive (BART / T5 / FLAN-T5 / mT5 fine-tune): NOT built.** It needs a labelled (chat -> manager-written summary) dataset that does not exist yet and would
   risk hallucination. `rouge.py` (ROUGE-1/2/L) is ready for when reference summaries exist; BERTScore and human evaluation are still to do.

## Reports
- **Daily:** progress and change, completed, new tasks, blocked, client pending opened/resolved, bugs reported/fixed, decisions, open risks, key messages.
- **Weekly (Mon-Sun):** per-day series, start/end progress, this vs previous week comparison (completed, new, messages, client items, bugs fixed, weight completed).
- **Full A-to-Z:** all 28 sections (executive summary ... next actions) + conflicts, weekly, daily and key messages. Timeline is built from actual evidence
  (first message, task creation/completion, deploys, client responses, decisions, requirement changes, meetings), each event with source message ids.
- **Exports:** JSON; CSV per table (Tasks, Client pending, Team performance, Risks, Bugs, Requirement changes, Conflicts, Timeline, Next actions);
  XLSX (summary + one sheet per table, evidence ids included); PDF (header with company/project/client/period, KPI cards, executive summary, tables, recommendations).
  Generated locally with openpyxl / reportlab; PDF text is escaped (markup in chat text cannot break the document).

## Validation
20 tests: extractive returns verbatim original messages only, chatter filtered, near-duplicates removed, period filters; summary grounded and tamper-detecting, handles
no-task chats; daily/weekly numbers cross-checked; all 28 sections present; timeline ordered with valid message ids; JSON round-trip; CSV/XLSX/PDF valid and contain evidence;
API endpoints for all formats. Bug found and fixed while testing: MMR picked four identical messages (redundancy penalty too weak) -> hard near-duplicate cut-off.

## Limits
- Wording is template-based and terse; PDF layout is functional, not designed (a branded layout is a Phase 10/11 task).
- The executive summary is only as good as the underlying extraction (Phase 5 limits). The `quality` claim flags how many tasks need review.
- Key-message selection quality has not been measured against human-chosen highlights.
