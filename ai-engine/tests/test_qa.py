from app.intelligence.pipeline import analyze
from app.intelligence.qa import is_question, question_type
from app.intelligence.types import Msg
from app.parsers.whatsapp import WhatsAppParser

ROLES = {"Priya": "CLIENT", "Rahul": "DEVELOPER", "Amit": "DEVELOPER"}


def run(lines):
    chat = "\n".join(f"{d}, {t} - {l}" for d, t, l in lines)
    msgs = [Msg.from_parsed(m) for m in WhatsAppParser().parse_text(chat)]
    return analyze(msgs, role_overrides=ROLES)["qa"]


def by_text(qa, part):
    return next(x for x in qa["items"] if part in x["text"])


def test_question_detection_english_hinglish_hindi_and_non_questions():
    for t in ("When will the API be ready?", "API kab ready hoga?", "Is task ka owner kaun hai", "Payment ka issue fix hua?", "भुगतान कब होगा?", "Can you share the invoice?"):
        assert is_question(t)[0], t
    for t in ("ok?", "hai na?", "Please share the link", "<Media omitted>", "Done", "Rahul?", "Deploy this tonight."):
        assert not is_question(t)[0], t
    assert question_type("API kab ready hoga?") == "when" and question_type("Is the build ready?") == "status" and question_type("Who owns billing?") == "who"


def test_answered_with_evidence_and_response_time():
    qa = run([("01/06/2026", "10:00", "Priya: Rahul, API kab ready hoga?"),
              ("01/06/2026", "10:05", "Rahul: API Friday tak ready ho jayega")])
    x = by_text(qa, "API kab")
    assert x["status"] == "ANSWERED" and x["answered_by"] == "Rahul" and x["response_minutes"] == 5.0
    assert x["evidence_message_ids"][0] == x["question_message_id"] and len(x["evidence_message_ids"]) == 2
    assert qa["stats"]["answered"] == 1 and qa["stats"]["median_response_minutes"] == 5.0


def test_acknowledgement_does_not_answer_a_content_question():
    qa = run([("01/06/2026", "10:00", "Priya: When will the payment gateway be live?"), ("01/06/2026", "10:01", "Rahul: ok")])
    assert by_text(qa, "payment gateway")["status"] == "UNANSWERED" and qa["stats"]["unanswered"] == 1


def test_unrelated_reply_does_not_count_as_answer():
    qa = run([("01/06/2026", "10:00", "Priya: When will the payment gateway be live?"),
              ("01/06/2026", "10:02", "Amit: lunch at 1 anyone"), ("01/06/2026", "10:03", "Rahul: the logo is in the drive folder")])
    assert by_text(qa, "payment gateway")["status"] != "ANSWERED"


def test_possible_answers_are_not_counted_and_are_flagged():
    qa = run([("01/06/2026", "10:00", "Priya: Is the invoice export working?"), ("01/06/2026", "10:40", "Rahul: yes")])
    x = by_text(qa, "invoice export")
    assert x["status"] in ("POSSIBLY_ANSWERED", "UNANSWERED") and qa["stats"]["answered"] == 0
    if x["status"] == "POSSIBLY_ANSWERED":
        assert x["needs_review"]


def test_polar_question_answered_when_the_reply_is_on_topic():
    qa = run([("01/06/2026", "10:00", "Priya: Is the invoice export working now?"), ("01/06/2026", "10:08", "Rahul: Yes, the invoice export is working now")])
    assert by_text(qa, "invoice export")["status"] == "ANSWERED"


def test_own_followup_never_answers_and_stats_by_role():
    qa = run([("01/06/2026", "10:00", "Priya: Who owns the billing module?"), ("01/06/2026", "10:01", "Priya: anyone?"),
              ("01/06/2026", "10:20", "Amit: I own the billing module")])
    x = by_text(qa, "billing module")
    assert x["status"] == "ANSWERED" and x["answered_by"] == "Amit"
    assert qa["stats"]["by_asker_role"]["CLIENT"]["asked"] >= 1


def test_client_questions_left_unanswered_are_counted_separately():
    qa = run([("01/06/2026", "10:00", "Priya: Where is the staging link?"), ("03/06/2026", "09:00", "Rahul: standup notes are up")])
    assert qa["stats"]["client_questions_unanswered"] == 1 and by_text(qa, "staging link")["age_hours"] is not None
