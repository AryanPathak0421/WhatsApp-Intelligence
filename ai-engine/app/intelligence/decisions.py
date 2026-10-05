"""Decisions and meetings (rule-based, evidence-linked)."""
from __future__ import annotations

import hashlib
import re

from app.intelligence.rules import signals
from app.intelligence.temporal import extract_deadline
from app.intelligence.topics import ALIASES, topic_set
from app.intelligence.types import ENGINE_VERSION, Msg


def _impact(text: str):
    ts = topic_set(text)
    g = [x[1:] for x in ts if x.startswith("@")]
    return g[0] if g else None


def detect_decisions(msgs: list[Msg], roles: dict) -> list[dict]:
    out = []
    for m in msgs:
        if not m.sender:
            continue
        s = signals(m.text)
        if not (s["decision"] or (m.category == "DECISION" and m.cat_conf >= 0.6)) or s["question"]:
            continue
        title = re.sub(r"^\s*(?:final(?:ised|ized)?|decision)\s*[:\-]?\s*", "", m.text.strip(), flags=re.I)[:160]
        out.append({"id": "dc_" + hashlib.sha1(m.id.encode()).hexdigest()[:10], "title": title,
                    "decided_by": m.sender, "decided_by_role": roles.get(m.sender, {}).get("role"),
                    "decided_at": m.ts, "impact": _impact(m.text), "confidence": 0.7 if re.search(r"decid|final", m.text, re.I) else 0.55,
                    "source_message_ids": [m.id], "model_version": ENGINE_VERSION})
    return out


def detect_meetings(msgs: list[Msg], roles: dict) -> list[dict]:
    out = []
    for m in msgs:
        if not m.sender:
            continue
        s = signals(m.text)
        if not s["meeting"] or s["question"] or not re.search(r"\b(?:meeting|call|demo|sprint planning|standup|sync)\b", m.text, re.I):
            continue
        when = extract_deadline(m.text, m.ts)
        if not when and not re.search(r"\b(?:schedule|rakh|tomorrow|today|kal|aaj|at \d)", m.text, re.I):
            continue
        out.append({"id": "mt_" + hashlib.sha1(m.id.encode()).hexdigest()[:10], "title": m.text.strip()[:140],
                    "organised_by": m.sender, "scheduled_text": when.text if when else None,
                    "scheduled_at": when.when if when else None, "mentioned_at": m.ts,
                    "confidence": 0.7 if when else 0.5, "source_message_ids": [m.id], "model_version": ENGINE_VERSION})
    return out
