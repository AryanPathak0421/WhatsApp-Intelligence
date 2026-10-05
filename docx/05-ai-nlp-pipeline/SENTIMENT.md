# Sentiment, frustration and urgency

Code: `ai-engine/app/intelligence/sentiment.py` (`result["sentiment"]`, snapshot kind `SENTIMENT`, `GET /api/projects/:id/sentiment`, **Insights -> Tone** tab).

## Method (transparent, model-free)
A word-list baseline for English, Hinglish and Devanagari Hindi:
- positive / negative lexicons (strong positives weigh 1.5), emoji cues, "not working" handling, negation window of 3 tokens ("not good" -> negative, "not bad" -> mildly positive, "no issue" -> not negative);
- **frustration** cues: "again/still ... not", "wrong again", "how many times", "kab tak", "abhi tak nahi", repeated `!!!`/`???`, shouting with negativity;
- **urgency** cues: urgent, asap, immediately, jaldi, turant, "by EOD", "aaj hi", ... (1.0 when emphasised).
Output per message: `label` (POSITIVE / NEUTRAL / NEGATIVE), `score` in [-1,1], `frustration` bool, `urgency` 0..1, and `evidence` = the cue words used. **No cue means NEUTRAL.**
Aggregates (counts, per sender, per day, client sentiment, frustration by sender) are arithmetic. Only non-neutral/frustrated/urgent messages are listed as `items` (top 200, most intense first).

## How reliable is it? (honest)
- Checked on **31 author-written examples** (`ai-engine/tests/test_sentiment.py`); the test requires >= 85% and passes. That measures that the rules do what the author intended, **not** accuracy on real chats.
- On the real HG chat 245 of 254 messages came out NEUTRAL, 3 positive, 6 negative, 1 frustrated. Much of that chat is Devanagari/Hinglish with little emotive vocabulary, so the baseline under-detects.
- **Not handled:** sarcasm, irony, context across messages, domain words that are negative only here ("issue" in "no issue" is handled, "issue" in "payment issue" counts negative on purpose).
- Use it to surface messages worth a look, never as a score of a person. The UI states this next to the numbers.

## What would make it measurable
A human-labelled set of real messages (a few hundred, double-annotated; the annotation tool already supports a sentiment-free category workflow and kappa), then compare this baseline with a
multilingual classifier fine-tuned on it. Until then no accuracy claim is made.
