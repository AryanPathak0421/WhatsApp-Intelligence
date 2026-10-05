"""Potential-contradiction detection. Never declares a winner: status = NEEDS_VERIFICATION."""
from __future__ import annotations

import hashlib
import re
from datetime import timedelta

from app.intelligence.rules import REJECT, norm, signals
from app.intelligence.topics import topic_overlap, topic_set
from app.intelligence.types import ENGINE_VERSION, Msg

STATE_POS = re.compile(r"(?<!\w)(?:completed?|done|finished|ready|available|reachable|working (?:fine|now|as expected)|is working|up and running|accessible|live|deployed|implemented|ho gaya|ho gya|kar diya)(?!\w)", re.I)
STATE_NEG = re.compile(r"(?:not|isn't|aren't|wasn't|n't|nahi|nhi|never) (?:yet )?(?:been )?(?:completed?|done|finished|ready|available|working|accessible|reachable|responding|live|deployed|implemented|started)|(?<!\w)(?:unavailable|down|broken|incomplete|abhi tak (?:nahi|nhi))(?!\w)|nahi (?:chal|mila|hua|hai)", re.I)
APPROVAL_POS = re.compile(r"(?<!\w)(?:approved|approve kar|green signal|signed off|sign-?off (?:done|given)|accepted)(?!\w)", re.I)
APPROVAL_NEG = re.compile(r"(?:not|hasn't|haven't|hasnt|never|nahi|nhi) (?:yet )?(?:approved|approve|signed off|accepted)|approval (?:is )?(?:still )?pending|approve nahi", re.I)
GENERIC = {"api", "client", "design", "module", "feature", "page", "app", "server", "system", "work", "project"}


def _assertions(msgs):
    out = []
    for m in msgs:
        if not m.sender:
            continue
        low = norm(m.text)
        topic = topic_set(m.text, extra_stop=GENERIC | {"completed", "approved", "available", "working", "not"})
        topic_full = topic_set(m.text)
        sig = signals(m.text)
        for dim, pos, neg in (("approval", APPROVAL_POS, APPROVAL_NEG), ("state", STATE_POS, STATE_NEG)):
            n, p = bool(neg.search(low)), bool(pos.search(low))
            if dim == "approval":
                n = n or sig["reject"]
            if dim == "state":
                if sig["question"]:
                    continue
                if n:
                    p = False  # "not working" must not count as "working"
            if p == n:
                continue
            out.append({"dim": dim, "pol": +1 if p else -1, "topic": topic_full, "core": topic, "m": m})
    return out


def detect_conflicts(msgs: list[Msg], window_days: int = 7) -> list[dict]:
    A = _assertions(msgs)
    found, seen = [], set()
    for j, b in enumerate(A):
        for k in range(j - 1, -1, -1):   # walk back only while inside the time window (no list copies)
            a = A[k]
            if b["m"].ts - a["m"].ts > timedelta(days=window_days):
                break
            if a["dim"] != b["dim"] or a["pol"] == b["pol"] or a["m"].sender == b["m"].sender:
                continue
            ov = topic_overlap(a["topic"], b["topic"])
            core_shared = a["core"] & b["core"]
            if ov < 0.5 or (not core_shared and not (a["topic"] & b["topic"] - {"@api"})):
                continue
            key = (a["m"].id, b["m"].id)
            if key in seen:
                continue
            seen.add(key)
            gap_h = (b["m"].ts - a["m"].ts).total_seconds() / 3600
            if a["pol"] > 0:      # claimed positive, later someone says negative -> real conflict
                sev = "HIGH" if a["dim"] == "approval" or ov >= 0.7 else "MEDIUM"
            else:                 # negative then positive: usually just progress unless very close
                if gap_h > 1:
                    continue
                sev = "LOW"
            topic_label = " ".join(sorted(x for x in (core_shared or (a["topic"] & b["topic"])) if not x.startswith("@"))) or "unspecified"
            found.append({
                "id": "cf_" + hashlib.sha1((a["m"].id + b["m"].id).encode()).hexdigest()[:10],
                "title": "Potential contradiction detected", "topic": topic_label, "dimension": a["dim"],
                "statement_a": {"author": a["m"].sender, "text": a["m"].text, "at": a["m"].ts, "message_id": a["m"].id},
                "statement_b": {"author": b["m"].sender, "text": b["m"].text, "at": b["m"].ts, "message_id": b["m"].id},
                "severity": sev, "status": "NEEDS_VERIFICATION",
                "confidence": round(min(0.8, 0.4 + 0.4 * ov), 2),
                "source_message_ids": [a["m"].id, b["m"].id], "model_version": ENGINE_VERSION})
    return found
