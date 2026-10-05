from app.intelligence.pipeline import analyze
from app.intelligence.types import Msg
from app.parsers.whatsapp import WhatsAppParser

ROLES = {"Priya": "CLIENT", "Rahul": "DEVELOPER", "Amit": "DEVELOPER"}

CHAT = [
    ("01/06/2026", "10:00", "Priya: Rahul please build the login page by Friday"),
    ("01/06/2026", "10:05", "Rahul: ok, working on the login page"),
    ("01/06/2026", "11:00", "Priya: When will the invoice export be ready?"),
    ("02/06/2026", "10:00", "Rahul: login page is done and deployed"),
    ("02/06/2026", "10:30", "Priya: This is wrong again, still not working!!!"),
    ("09/06/2026", "10:00", "Priya: Amit please fix the payment bug"),
    ("09/06/2026", "12:00", "Amit: payment bug fixed"),
    ("03/07/2026", "10:00", "Priya: Rahul please add the dashboard filters"),
    ("03/07/2026", "10:10", "Rahul: working on the dashboard filters"),
]


def result():
    chat = "\n".join(f"{d}, {t} - {l}" for d, t, l in CHAT)
    msgs = [Msg.from_parsed(m) for m in WhatsAppParser().parse_text(chat)]
    return analyze(msgs, role_overrides=ROLES)


def test_hierarchy_days_weeks_months_and_counts_add_up():
    p = result()["periodic"]
    assert [d["key"] for d in p["daily"]] == ["2026-06-01", "2026-06-02", "2026-06-09", "2026-07-03"]
    assert [w["key"] for w in p["weekly"]] == ["2026-W23", "2026-W24", "2026-W27"]
    assert [m["key"] for m in p["monthly"]] == ["2026-06", "2026-07"]
    assert sum(d["stats"]["messages"] for d in p["daily"]) == 9
    june = next(m for m in p["monthly"] if m["key"] == "2026-06")
    assert june["stats"]["messages"] == 7 == sum(w["stats"]["messages"] for w in p["weekly"] if w["key"] in ("2026-W23", "2026-W24"))
    assert june["trend"] is None and p["monthly"][1]["trend"]["messages_vs_previous_month_pct"] == round(100 * (2 - 7) / 7, 1)


def test_every_highlight_is_backed_by_message_ids_and_text_mentions_only_found_facts():
    p = result()["periodic"]
    for level in ("daily", "weekly", "monthly"):
        for period in p[level]:
            assert all(h["source_message_ids"] for h in period["highlights"]), (level, period["key"])
            assert set(period["evidence_message_ids"]) >= {m for h in period["highlights"][:5] for m in h["source_message_ids"]}
    d1 = p["daily"][0]
    assert "login" in d1["text"].lower() and "messages from" in d1["text"]
    assert "Bugs fixed" not in d1["text"]                                 # nothing was fixed that day: the summary must not invent it


def test_open_questions_and_tone_are_reported_with_the_right_labels():
    p = result()["periodic"]
    day2 = next(d for d in p["daily"] if d["key"] == "2026-06-02")
    assert day2["stats"]["frustrated"] >= 1 and "Tone (lexicon baseline)" in day2["text"]
    day1 = next(d for d in p["daily"] if d["key"] == "2026-06-01")
    assert any(h["kind"] == "question_open" for h in day1["highlights"])


def test_weekly_merges_dedupe_items_seen_in_two_days():
    w = next(w for w in result()["periodic"]["weekly"] if w["key"] == "2026-W23")
    ids = [tuple(h["source_message_ids"]) for h in w["highlights"] if h["kind"] == "task_created"]
    assert len(ids) == len(set(ids))
