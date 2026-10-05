"""Bug lifecycle and commitment tracking."""
from __future__ import annotations

import hashlib
from bisect import bisect_right
import re
from datetime import datetime, timedelta
from typing import Optional

from app.intelligence.rules import signals
from app.intelligence.temporal import extract_deadline
from app.intelligence.topics import find_people, topic_overlap, topic_set
from app.intelligence.types import ENGINE_VERSION, Msg

INVESTIGATING = re.compile(r"\b(?:looking into|checking|investigating|will check|will look|on it|dekh raha|dekh rahi|dekhta hu|dekhti hu|dekh lunga|dekh leta hu)\b", re.I)
COMMIT_ACTION = re.compile(r"(?:i will|i'll|will|kar dunga|kar dungi|bhej dunga|bhej dungi)\s+(.+)", re.I)


def detect_bugs(msgs: list[Msg], roles: dict, tasks) -> list[dict]:
    bugs: list[dict] = []
    by_token: dict[str, list] = {}
    for t in tasks:
        for tok in t.topic:
            by_token.setdefault(tok, []).append(t)

    def new_bug(m, topic):
        pool = {id(t): t for tok in topic for t in by_token.get(tok, ())}          # only tasks sharing a token can overlap
        cand = sorted(pool.values(), key=lambda t: t.created_at, reverse=True)[:200]
        lk = max(((topic_overlap(topic, t.topic), t) for t in cand), key=lambda x: x[0], default=(0, None))
        bugs.append({"id": "bug_" + hashlib.sha1(m.id.encode()).hexdigest()[:10], "title": m.text.strip()[:140],
                     "_topic": topic, "status": "OPEN", "reported_by": m.sender, "reported_at": m.ts,
                     "task_id": lk[1].id if lk[0] >= 0.4 else None, "fixed_at": None, "assignee": None,
                     "history": [{"status": "OPEN", "message_id": m.id, "at": m.ts}],
                     "source_message_ids": [m.id], "confidence": 0.7, "model_version": ENGINE_VERSION})

    def match(topic, states, ts):
        c = [(topic_overlap(b["_topic"], topic), b) for b in bugs if b["status"] in states]
        c = [x for x in c if x[0] >= 0.4]
        return max(c, key=lambda x: (x[0], x[1]["reported_at"]))[1] if c else None

    def owned_by(sender, states):
        mine = [b for b in bugs if b["assignee"] == sender and b["status"] in states]
        return max(mine, key=lambda b: b["reported_at"]) if mine else None

    def move(b, status, m):
        b["status"] = status
        b["history"].append({"status": status, "message_id": m.id, "at": m.ts})
        b["source_message_ids"].append(m.id)
        if status == "FIXED":
            b["fixed_at"] = m.ts

    for m in msgs:
        if not m.sender:
            continue
        s = signals(m.text)
        topic = topic_set(m.text, extra_stop=("bug", "issue", "error", "crash", "found", "fixed", "resolved"))
        if s["reopen"]:
            b = match(topic, {"FIXED", "TESTING", "CLOSED"}, m.ts)
            if b:
                move(b, "REOPENED", m)
            continue
        if s["bug_fixed"] and (s["bug"] or topic):
            b = match(topic, {"OPEN", "INVESTIGATING", "IN_PROGRESS", "REOPENED"}, m.ts) or owned_by(m.sender, {"INVESTIGATING", "IN_PROGRESS", "REOPENED"})
            if b:
                move(b, "FIXED", m)
                continue
        if s["test_pass"] or (s["weak_done"] and not topic):
            b = match(topic, {"FIXED"}, m.ts) or (max((x for x in bugs if x["status"] == "FIXED"), key=lambda x: x["fixed_at"], default=None)
                                                  if not topic and s["test_pass"] is not None and any(x["status"] == "FIXED" for x in bugs) else None)
            if b:
                move(b, "CLOSED", m)
                continue
        if INVESTIGATING.search(m.text):
            b = match(topic, {"OPEN", "REOPENED"}, m.ts)
            if b is None and len(m.text.split()) <= 6:   # short acknowledgement ("dekhta hu", "on it") right after a bug report by someone else
                recent = [x for x in bugs if x["status"] == "OPEN" and x["reported_by"] != m.sender and (m.ts - x["reported_at"]).total_seconds() < 3 * 3600]
                b = max(recent, key=lambda x: x["reported_at"]) if recent else None
            if b:
                move(b, "INVESTIGATING", m)
                b["assignee"] = m.sender
                continue
        if s["progress"]:
            b = match(topic, {"OPEN", "INVESTIGATING"}, m.ts)
            if b:
                move(b, "IN_PROGRESS", m)
                b["assignee"] = m.sender
                continue
        if (s["bug"] or m.category == "BUG" and m.cat_conf >= 0.6) and not s["bug_fixed"] and not s["question"]:
            if topic and not match(topic, {"OPEN", "INVESTIGATING", "IN_PROGRESS", "REOPENED"}, m.ts):
                new_bug(m, topic)
    for b in bugs:
        b.pop("_topic")
    return bugs


def detect_commitments(msgs: list[Msg], roles: dict, tasks, as_of: Optional[datetime] = None) -> list[dict]:
    as_of = as_of or (msgs[-1].ts if msgs else datetime.utcnow())
    out = []
    stamps = [x.ts for x in msgs]
    for m in msgs:
        if not m.sender:
            continue
        s = signals(m.text)
        if not s["commit"] or s["question"] or s["done"]:
            continue
        mm = COMMIT_ACTION.search(m.text)
        action = (mm.group(1) if mm else m.text).strip()
        dl = extract_deadline(m.text, m.ts)
        topic = topic_set(action)
        if not topic:
            continue
        status, fulfilled_at, evid = "PENDING", None, [m.id]
        for later in msgs[bisect_right(stamps, m.ts):]:   # msgs are time-ordered: start after m, stop after 14 days
            if later.ts - m.ts > timedelta(days=14):
                break
            if later.sender != m.sender:
                continue
            ls = signals(later.text)
            if ls["done"] and topic_overlap(topic, topic_set(later.text)) >= 0.3:
                status, fulfilled_at = "FULFILLED", later.ts
                evid.append(later.id)
                break
        if status == "PENDING" and dl and dl.when and dl.when < as_of:
            status = "MISSED"
        out.append({"id": "cm_" + hashlib.sha1(m.id.encode()).hexdigest()[:10], "person": m.sender,
                    "action": action[:140], "deadline_text": dl.text if dl else None,
                    "deadline": dl.when if dl else None, "status": status, "fulfilled_at": fulfilled_at,
                    "confidence": round(0.55 + (0.2 if dl else 0) + (0.1 if status == "FULFILLED" else 0), 2),
                    "source_message_ids": evid, "model_version": ENGINE_VERSION})
    return out
