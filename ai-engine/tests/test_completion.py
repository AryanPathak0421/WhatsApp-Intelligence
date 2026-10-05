from app.intelligence.pipeline import analyze
from app.intelligence.types import Msg
from app.parsers.whatsapp import WhatsAppParser
from app.intelligence.completion import _announces


def run(lines, roles=None):
    chat = "\n".join(f"{d}, 10:{i:02d} - {l}" for i, (d, l) in enumerate(lines))
    msgs = [Msg.from_parsed(m) for m in WhatsAppParser().parse_text(chat)]
    return analyze(msgs, role_overrides=roles or {"Priya": "CLIENT", "Rahul": "DEVELOPER"})


BASE = [("01/06/2026", "Priya: Rahul please build the login page by Friday"),
        ("02/06/2026", "Priya: Rahul also make the invoice export"),
        ("03/06/2026", "Rahul: ok on it")]


def test_announcement_phrases():
    for t in ("Person H project is live and deployed", "Person H project is completed.", "website deployed and live",
              "Project complete ho gaya hai", "Must check, everything is live"):
        assert _announces(t), t
    for t in ("once the project is live we will invoice", "project is not completed yet", "website will be deployed tomorrow",
              "login page is done", "if everything is live let me know"):
        assert not _announces(t), t


def test_project_completion_closes_open_tasks_and_flags_them_for_review():
    r = run(BASE + [("20/06/2026", "Rahul: Priya project is live and deployed, please check")])
    pc = r["project_completion"]
    assert pc["state"] == "CLAIMED" and len(pc["closed_task_ids"]) == len([t for t in r["tasks"]]) >= 1
    for t in r["tasks"]:
        assert t["status"] == "COMPLETED" and t["needs_review"]
        assert any("project-completion" in x for x in t["review_reasons"])
    assert r["progress"]["overall"] == 100.0


def test_client_pushback_after_announcement_disputes_it_and_closes_nothing():
    r = run(BASE + [("20/06/2026", "Rahul: project is live and deployed"), ("21/06/2026", "Priya: the login page is not working, error on submit")])
    assert r["project_completion"]["state"] == "DISPUTED"
    assert all(t["status"] != "COMPLETED" for t in r["tasks"])


def test_client_saying_it_is_complete_is_not_a_delivery_claim():
    r = run(BASE + [("20/06/2026", "Priya: the project is completed on our side")])
    assert r["project_completion"] is None
    assert all(t["status"] != "COMPLETED" for t in r["tasks"])
