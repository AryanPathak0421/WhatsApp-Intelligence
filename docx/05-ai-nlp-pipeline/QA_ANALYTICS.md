# Question / answer analytics

Code: `ai-engine/app/intelligence/qa.py` (called from `pipeline.analyze` as `result["qa"]`). Stored as snapshot kind `QA`; served by `GET /api/projects/:id/qa`; shown in the
**Insights -> Questions** tab. Deterministic, no model.

## What it answers
Who asked, whether it was answered, by whom, how long it took, and what is still open (with age and whether the asker was the client).

## Question detection (`is_question`)
A message is a question if it contains `?` (with a wh-word or at least 3 words) or has an interrogative word (kya, kab, kaun, kaise, kyun, kitna, kahan, what, when, who, how, why, ...,
and Devanagari forms) together with a polar opener. Not questions: tag questions ("ok?", "hai na?"), one-word queries, `<Media omitted>`, `<url>`-only, mention-only messages.
Each gets a confidence (0.92 wh+`?`, 0.85 `?`, 0.6 weak).

Question types drive what an answer must look like: `when` (a date/time), `who` (a person/ownership statement), `status` (done/ready/progress/number), `artifact` (link/file),
`polar` (yes/no or an affirmative; includes request-shaped questions "can we ...?", "is this okay?"), otherwise `wh`.

## Answer matching (evidence score 0..1)
Candidates are the next messages (max 40, within 48 h) from a **different** sender. Score = addressed person replied (+0.35) + topical overlap with the question (up to +0.4)
+ answer-shaped content for the question type (+0.2..0.35) + closeness in time for the first real reply (+0.15 within 10 min, +0.1 within 1 h, +0.05 within 6 h; half for later ones);
a counter-question is halved. Bare acknowledgements ("ok", "hmm", "thanks", "noted") never answer a content question; for polar questions an affirmative does.

| Score | Status | Counted as answered? |
|---|---|---|
| >= 0.5 | `ANSWERED` | yes |
| 0.3 - 0.5 | `POSSIBLY_ANSWERED` (`needs_review`) | **no** |
| < 0.3 | `UNANSWERED` (with `age_hours`) | no |

Output per question: `id, question_message_id, asked_by, asker_role, asked_at, text, type, status, answer_message_id, answered_by, answerer_role, response_minutes, confidence, needs_review, reasons[], age_hours, evidence_message_ids[]`.
Stats: `total_questions, answered, possibly_answered, unanswered, answer_rate, median/mean_response_minutes, client_questions_unanswered, by_asker_role, oldest_unanswered_hours`.

## Measured behaviour
- 8 unit tests (`ai-engine/tests/test_qa.py`) on hand-written chats: detection (EN/Hinglish/Hindi), answered with evidence and response time, ack does not answer, unrelated reply does not count,
  weak match stays unconfirmed, polar on-topic reply answers, client questions left open are counted separately.
- On the real HG chat (20 questions found): 7 answered, 7 possibly answered, 6 unanswered. **Not independently verified**; the chat's answers are mostly "Okay"-style replies and
  group-call arrangements, which is exactly where rule-based matching is weakest. Treat `POSSIBLY_ANSWERED` as "a human should look".

## Known limits
Answers that arrive after 48 h or beyond 40 messages are not found; answers given as a reply to a different message than the nearest question may be attributed to the wrong question when two
questions are close together; media-only answers count only for `artifact` questions; sarcasm and rhetorical questions are not detected.
