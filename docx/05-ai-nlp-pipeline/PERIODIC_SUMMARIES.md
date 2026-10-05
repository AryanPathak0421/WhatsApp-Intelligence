# Hierarchical daily / weekly / monthly summaries

Code: `ai-engine/app/summarization/periodic.py` (`result["periodic"]`, snapshot kind `PERIODIC`, `GET /api/projects/:id/summaries?kind=`, **Insights -> Summaries** tab).

## Design
Summaries are assembled from **verified structured facts**, never by feeding the whole chat to a model.
1. **Day facts**: message and participant counts, top topics (topic-group tags), and evidence-linked items: tasks created / completed, decisions, bugs reported / fixed, possible conflicts,
   meetings, items waiting on the client, questions without a confirmed answer (from Q&A), frustrated/urgent messages (from sentiment).
2. **Week** (ISO week) = merge of its days; **month** = merge of its weeks. Merging sums counts, unions top-topic counters and de-duplicates items by their source message ids.
3. Month adds `recurring_topics` (topic present in 2+ weeks) and `trend` against the previous month (message volume %, completed-task delta).
4. The text is a template over those facts ("New tasks (2): ...; Decisions (1): ..."). Nothing is stated that is not in an item, and every highlight has `source_message_ids`;
   each period has `evidence_message_ids`.

## Output
`{daily:[], weekly:[], monthly:[], method}`; each period: `kind, key (2026-06-01 | 2026-W23 | 2026-06), start, end, stats{messages, participants, top_senders, n_<item kind>, negative, frustrated, urgent}, topics, highlights[], evidence_message_ids[], text`.
The API returns newest first and caps the list.

## Limits
- Extractive/templated: it will not paraphrase, explain causes or write fluent narrative. A generative layer over these facts is possible later, but must be checked against `source_message_ids`.
- Quality is bounded by the extractors it summarises (task/decision extraction is modest on real Hinglish chats; see `12-datasets-and-models`).
- Blockers/"risks this week" use only what the extractors produced; the project-level risk engine is separate.
- Days are limited to the most recent 400 per project.

Tests: `ai-engine/tests/test_periodic.py` (hierarchy and counts add up, every highlight has source ids and nothing is invented, open questions and tone appear, weekly merge de-duplicates)
and `backend/tests/insights.test.ts`.
