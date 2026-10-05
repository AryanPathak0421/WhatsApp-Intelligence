"""Regression tests for generic defects found by the unseen-chat benchmark (bench/unseen_eval.py)."""
from app.intelligence.pipeline import analyze
from app.intelligence.types import Msg
from app.parsers.whatsapp import WhatsAppParser


def run(text):
    return analyze([Msg.from_parsed(m) for m in WhatsAppParser().parse_text(text)])


def task(res, needle):
    return next(t for t in res["tasks"] if needle.lower() in t["title"].lower())


def test_assignment_in_a_later_sentence_of_the_message():
    r = run("01/10/2026, 10:00 - Rahul: Understood Dr. Rao. Tushar, reminders notification module please, by the 26th.\n"
            "01/10/2026, 10:01 - Tushar: ok\n")
    t = r["tasks"][0]
    assert t["assigned_to"] == "Tushar" and "reminder" in t["title"].lower() and "understood" not in t["title"].lower()


def test_at_mention_and_hinglish_imperatives():
    r = run("01/10/2026, 10:00 - Rahul: @Arjun can you build the catalogue API this week?\n"
            "01/10/2026, 10:01 - Pallavi: ji\n01/10/2026, 10:02 - Rahul: Pallavi donation page ka design bana do, kal tak\n")
    assert task(r, "catalogue")["assigned_to"] == "Arjun"
    d = task(r, "design")
    assert d["assigned_to"] == "Pallavi" and "bana do" not in d["title"]


def test_object_named_in_the_previous_sentence():
    r = run("03/06/2026, 10:13 - Manish: Theek hai, Razorpay final. Yash tum integrate karo, 15 June tak\n03/06/2026, 10:14 - Yash: Okay sir\n")
    assert "razorpay" in r["tasks"][0]["title"].lower()
    assert r["decisions"] and "razorpay" in r["decisions"][0]["title"].lower()


def test_volunteering_creates_a_task_for_the_volunteer():
    r = run("02/05/2026, 09:01 - Karthik: guys CRM integration for BrightMart - need an owner\n"
            "02/05/2026, 09:02 - Divya: I can take it\n")
    t = task(r, "crm")
    assert t["assigned_to"] == "Divya" and t["created_by"] == "Karthik"


def test_self_announced_task_is_flagged_for_review():
    r = run("18/05/2026, 09:10 - Tushar: I'll build the booking screen on the app side meanwhile.\n")
    t = task(r, "booking screen")
    assert t["assigned_to"] == "Tushar" and t["needs_review"] and any("self-announced" in x for x in t["review_reasons"])


def test_asking_the_client_is_pending_item_not_a_dev_task():
    chat = ("01/10/2026, 10:00 - Rahul: Amit, please build the checkout by Friday\n01/10/2026, 10:01 - Amit: ok\n"
            "01/10/2026, 10:02 - Mrs. Iyer: we need Razorpay for the trust account\n"
            "01/10/2026, 10:05 - Rahul: Mrs. Iyer please send the live keys\n"
            "01/10/2026, 11:00 - Sales - Neha: Mrs. Iyer hasn't shared the 80G certificate yet\n")
    r = run(chat)
    assert not any("iyer" in (t["assigned_to"] or "").lower() for t in r["tasks"])
    titles = " ".join(c["title"].lower() for c in r["client_pending"])
    assert "key" in titles and "80g" in titles and all(c["status"] == "OPEN" for c in r["client_pending"])


def test_client_supplying_the_item_resolves_it_but_unrelated_approval_does_not():
    chat = ("01/10/2026, 10:00 - Neha (Sales): Dr. Rao is yet to confirm the consultation fee structure.\n"
            "01/10/2026, 10:05 - Neha (Sales): Dr. Rao still hasn't sent the clinic logo\n"
            "01/10/2026, 11:00 - Dr. Rao: Design looks good, approved.\n"
            "01/10/2026, 11:30 - Dr. Rao: Fee structure attached.\n")
    r = run(chat)
    by = {("fee" if "fee" in c["title"].lower() else "logo"): c["status"] for c in r["client_pending"]}
    assert by["fee"] == "RESOLVED" and by["logo"] == "OPEN"


def test_bug_acknowledgement_links_a_later_fix_with_different_words():
    chat = ("10/04/2026, 11:30 - Imran (QA): login me ek bug mila - wrong OTP dene pe app crash ho jata hai\n"
            "10/04/2026, 11:35 - Sandeep: dekhta hu\n"
            "10/04/2026, 15:00 - Sandeep: crash fix kar diya, naya build upload kiya\n")
    b = run(chat)["bugs"][0]
    assert b["status"] == "FIXED" and b["assignee"] == "Sandeep"


def test_requirement_change_without_a_known_option_list():
    r = run("19/05/2026, 10:00 - Dr. Rao: Change of plan - we need WhatsApp reminders instead of SMS reminders for patients.\n")
    ch = r["requirement_changes"][0]
    assert "whatsapp" in ch["new_value"].lower() and "sms" in ch["old_value"].lower()


def test_state_conflict_with_reachability_wording():
    r = run("20/05/2026, 15:30 - Isha: Reminder service is deployed to staging.\n20/05/2026, 16:00 - Lakshmi: reminder service is not reachable on staging, getting timeouts\n")
    assert len(r["conflicts"]) == 1
