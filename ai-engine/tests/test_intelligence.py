from datetime import datetime

import pytest

from app.intelligence.pipeline import analyze
from app.intelligence.rules import has_done, signals
from app.intelligence.temporal import extract_deadline
from app.intelligence.types import Msg
from app.parsers.whatsapp import WhatsAppParser
from tests.scenario_chat import CHAT


@pytest.fixture(scope="module")
def result():
    msgs = [Msg.from_parsed(m) for m in WhatsAppParser().parse_text(CHAT)]
    return analyze(msgs)


def task(result, needle):
    return next(t for t in result["tasks"] if needle.lower() in t["title"].lower())


# --- temporal -----------------------------------------------------------------
BASE = datetime(2026, 10, 1, 10, 0)  # Thursday


@pytest.mark.parametrize("text,expected", [
    ("please do it by Friday", datetime(2026, 10, 2, 18, 0)),
    ("kal tak kar dena", datetime(2026, 10, 2, 18, 0)),
    ("deploy by 5 PM today", datetime(2026, 10, 1, 17, 0)),
    ("Monday tak", datetime(2026, 10, 5, 18, 0)),
    ("due 15th November", datetime(2026, 11, 15, 18, 0)),
    ("in 3 days", datetime(2026, 10, 4, 10, 0)),
])
def test_deadlines(text, expected):
    d = extract_deadline(text, BASE)
    assert d and d.when == expected and 0.3 <= d.confidence <= 0.95 and d.text


def test_no_deadline():
    assert extract_deadline("good morning team", BASE) is None


# --- rules ----------------------------------------------------------------------
def test_negated_completion():
    assert has_done("Frontend completed") == (True, False)
    assert has_done("not done yet")[0] is False
    assert has_done("integration abhi complete nahi hua")[0] is False


def test_hinglish_signals():
    assert signals("frontend complete ho gaya")["done"]
    assert signals("API ready hai but credentials nahi mile")["blocked"]
    assert signals("Client ka response abhi pending hai")["client_wait"]


# --- tasks / status ----------------------------------------------------------
def test_task_extraction_spec_example(result):
    t = task(result, "razorpay")
    assert t["assigned_to"] == "Amit" and t["created_by"] == "Rahul"
    assert t["deadline_text"] == "by Friday" and t["deadline"] == datetime(2026, 10, 2, 18, 0)
    assert t["confidence"] > 0.7


def test_multi_message_resolution_completes(result):
    t = task(result, "razorpay")
    assert t["status"] == "COMPLETED"
    assert len(t["evidence_message_ids"]) >= 4  # create + progress + integrated + tested
    assert [x["status"] for x in t["status_trace"]][-1] == "COMPLETED"


def test_dev_done_but_external_dependency_is_blocked(result):
    t = task(result, "login")
    assert t["status"] == "BLOCKED" and t["external_dependency"] == "credentials"


def test_unknown_assignee_flagged(result):
    t = task(result, "mockup")
    assert t["assigned_to"] == "Sneha" and t["needs_review"]


def test_client_requirement_is_not_a_task(result):
    assert not any("stripe" in t["title"].lower() for t in result["tasks"])


def test_ambiguous_done_never_completes():
    chat = ("01/10/2026, 10:00 - Rahul: Amit please integrate Razorpay by Friday\n"
            "01/10/2026, 11:00 - Amit: Done\n")
    r = analyze([Msg.from_parsed(m) for m in WhatsAppParser().parse_text(chat)])
    t = r["tasks"][0]
    assert t["status"] != "COMPLETED" and t["needs_review"]


# --- client pending -----------------------------------------------------------
def test_client_pending_open_and_resolved(result):
    by = {c["type"]: [] for c in result["client_pending"]}
    items = result["client_pending"]
    homepage = next(c for c in items if "homepage" in c["title"].lower())
    assert homepage["status"] == "RESOLVED" and homepage["resolution_message_id"]
    inv = next(c for c in items if "invoice" in c["title"].lower())
    assert inv["status"] == "OPEN" and inv["responsible"] == "CLIENT" and inv["age_days"] > 1
    assert homepage["source_message_ids"] and 0 < homepage["confidence"] <= 0.95


def test_response_time_pairs(result):
    r = result["client_response_time"]
    assert r["pairs"] >= 1 and r["min_hours"] <= r["avg_hours"] <= r["max_hours"]


# --- requirements / conflicts / bugs / commitments / risks ----------------------
def test_requirement_change_stripe_to_razorpay(result):
    ch = result["requirement_changes"]
    assert len(ch) == 1
    assert ch[0]["old_value"] == "stripe" and ch[0]["new_value"] == "razorpay"
    assert ch[0]["changed_by_role"] in ("CLIENT", "CLIENT_REPRESENTATIVE")
    v = next(r for r in result["requirements"] if r["key"] == "payment-provider")["versions"]
    assert [x["value"] for x in v] == ["stripe", "razorpay"]


def test_conflict_detected_not_adjudicated(result):
    cf = result["conflicts"]
    assert len(cf) == 1 and cf[0]["status"] == "NEEDS_VERIFICATION" and cf[0]["severity"] == "HIGH"
    assert "completed" in cf[0]["statement_a"]["text"] and "not available" in cf[0]["statement_b"]["text"]
    assert cf[0]["statement_a"]["author"] != cf[0]["statement_b"]["author"]


def test_no_false_conflict_on_normal_progress():
    chat = ("01/10/2026, 10:00 - Amit: Payment API not ready yet\n"
            "02/10/2026, 10:00 - Amit: Payment API is completed\n")
    r = analyze([Msg.from_parsed(m) for m in WhatsAppParser().parse_text(chat)])
    assert r["conflicts"] == []


def test_bug_lifecycle(result):
    b = result["bugs"]
    assert len(b) == 1 and b[0]["status"] == "CLOSED"
    assert [h["status"] for h in b[0]["history"]] == ["OPEN", "FIXED", "CLOSED"]


def test_commitment_fulfilled(result):
    c = next(c for c in result["commitments"] if c["person"] == "Amit")
    assert c["status"] == "FULFILLED" and c["deadline"] == datetime(2026, 10, 2, 17, 0)


def test_risk_explainable(result):
    r = result["risk"]
    assert 0 <= r["score"] <= 100 and r["level"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert abs(sum(f["contribution"] for f in r["factors"].values()) - r["score"]) < 0.6
    assert any("login" in k["title"].lower() and k["source_message_ids"] for k in r["risks"])


def test_every_derived_object_has_evidence(result):
    for t in result["tasks"]:
        assert t["source_message_id"] and t["evidence_message_ids"] and t["model_version"]
    for key in ("client_pending", "requirement_changes", "conflicts", "commitments", "bugs"):
        for o in result[key]:
            assert o["source_message_ids"] and o["model_version"] and "confidence" in o


def test_progress_message_mentioning_production_does_not_complete():
    chat = ("01/10/2026, 10:00 - Rahul: Amit please prepare production deployment by Friday\n"
            "01/10/2026, 11:00 - Amit: Working on production deployment now.\n")
    r = analyze([Msg.from_parsed(m) for m in WhatsAppParser().parse_text(chat)])
    assert r["tasks"][0]["status"] == "IN_PROGRESS"
