"""Sanity checks of the lexicon baseline on AUTHOR-WRITTEN examples (not independent ground truth)."""
import pytest

from app.intelligence.sentiment import analyze_sentiment, score_message
from app.intelligence.types import Msg
from datetime import datetime

CASES = [
    # (text, label)
    ("Thanks a lot, the demo looks great!", "POSITIVE"), ("Perfect, this is exactly what we wanted", "POSITIVE"), ("Bahut badhiya kaam kiya aapne", "POSITIVE"),
    ("Shukriya, mast lag raha hai", "POSITIVE"), ("बहुत बढ़िया, धन्यवाद", "POSITIVE"), ("Awesome work team 👍", "POSITIVE"), ("Really appreciate the quick fix", "POSITIVE"),
    ("Excellent, deployment was smooth", "POSITIVE"), ("Happy with the progress 😊", "POSITIVE"), ("Zabardast, ye sahi hai", "POSITIVE"),
    ("This is wrong again, same issue as before", "NEGATIVE"), ("The payment page is not working", "NEGATIVE"), ("Ye kharab hai, kaam nahi kar raha", "NEGATIVE"),
    ("Very disappointed with the delay", "NEGATIVE"), ("Worst experience, nothing works", "NEGATIVE"), ("Galat result aa raha hai, dikkat hai", "NEGATIVE"),
    ("यह गलत है, बहुत परेशान हूँ", "NEGATIVE"), ("The app crashed again 😡", "NEGATIVE"), ("Still broken, this is useless", "NEGATIVE"), ("Why is the bug still there?!!!", "NEGATIVE"),
    ("Not good, the layout is broken", "NEGATIVE"), ("not happy with this", "NEGATIVE"),
    ("Ok", "NEUTRAL"), ("I will send the file tomorrow", "NEUTRAL"), ("Meeting at 5 pm", "NEUTRAL"), ("Kal deployment kar dena", "NEUTRAL"), ("<Media omitted>", "NEUTRAL"),
    ("Please share the invoice link", "NEUTRAL"), ("No issue, everything is fine here", "POSITIVE"), ("Koi dikkat nahi, sab theek hai", "NEUTRAL"),
    ("Check the report", "NEUTRAL"), ("API ka status kya hai", "NEUTRAL"),
]


def test_lexicon_baseline_on_author_written_examples():
    wrong = [(t, want, score_message(t)["label"]) for t, want in CASES if score_message(t)["label"] != want]
    acc = 1 - len(wrong) / len(CASES)
    assert acc >= 0.85, f"accuracy {acc:.2f}; wrong: {wrong}"


def test_negation_flips_and_no_problem_is_not_negative():
    assert score_message("not good")["label"] == "NEGATIVE"
    assert score_message("no issue at all")["label"] != "NEGATIVE"
    assert score_message("not bad")["score"] >= 0


def test_frustration_and_urgency_have_evidence():
    r = score_message("This is URGENT!! Still not fixed, how many times do I have to ask")
    assert r["frustration"] and r["urgency"] >= 0.7 and r["evidence"]
    assert score_message("jaldi karo, turant chahiye")["urgency"] >= 0.7
    assert score_message("kal dekhte hain")["urgency"] == 0


def test_neutral_by_default_and_evidence_lists_the_words_used():
    r = score_message("Please update the document")
    assert r["label"] == "NEUTRAL" and r["score"] == 0 and r["evidence"] == []
    assert "great" in score_message("great job")["evidence"]


def test_aggregation_counts_and_client_sentiment():
    t0 = datetime(2026, 6, 1, 10)
    msgs = [Msg("1", t0, "Priya", "This is wrong again, very disappointed", 0), Msg("2", t0, "Rahul", "Sorry, fixing it now", 1),
            Msg("3", t0, "Priya", "Thanks, perfect now", 2), Msg("4", t0, "Rahul", "<Media omitted>", 3)]
    out = analyze_sentiment(msgs, {"Priya": {"role": "CLIENT"}, "Rahul": {"role": "DEVELOPER"}})
    c = out["counts"]
    assert c["messages_scored"] == 3 and c["NEGATIVE"] == 1 and c["POSITIVE"] == 1 and c["NEUTRAL"] == 1
    assert out["client_sentiment"]["NEGATIVE"] == 1 and out["client_sentiment"]["POSITIVE"] == 1 and out["frustration_by_sender"] == {"Priya": 1}
    assert all("message_id" in x for x in out["items"])
