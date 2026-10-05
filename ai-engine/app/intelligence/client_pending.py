"""Client-pending engine: open dependency items, auto-resolution, response times."""
from __future__ import annotations

import hashlib
import re
import statistics
from datetime import datetime, timedelta
from typing import Optional

from app.intelligence.roles import CLIENT_SIDE
from app.intelligence.rules import APPROVAL, CLIENT_WAIT, client_pending_type, norm, signals
from app.intelligence.tasks import task_weight
from app.intelligence.topics import find_people, tokens, topic_overlap, topic_set
from app.intelligence.types import ENGINE_VERSION, Msg

PROVIDED = re.compile(r"\b(?:shared|sent|sending|here (?:is|are)|attached|uploaded|provided|received|mil gaya|mil gaye|bhej diya|bhej diye|bheja|de diya|diya hai)\b", re.I)
NAMED_REQUEST = re.compile(r"\b(?:please|pls|plz|kindly|can you|could you|bhej(?:o| do)?|share|send|confirm|regenerate|provide|reply|respond)\b", re.I)
NAMED_NEG = re.compile(r"(?:hasn'?t|haven'?t|has not|have not|did not|didn'?t|yet to|still (?:not|waiting)|no reply|nahi|nhi)\W+.{0,25}?\b(?:sent|send|share|shared|reply|replied|respond|responded|confirm|confirmed|provide|provided|bhej|bheja|diya)\b|\b(?:sent|send|share|shared|reply|replied|respond|responded|confirm|confirmed|provide|provided)\b.{0,12}?\b(?:yet|nahi|nhi)\b|no reply", re.I)
PAID = re.compile(r"\b(?:paid|transferred|payment (?:done|received|made)|advance (?:sent|received)|transfer kar diya)\b", re.I)
REQUEST = re.compile(r"\?|\b(?:please|kindly|pls|confirm|share|send|approve|review|let us know|bataiye|batao)\b", re.I)
LEVELS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]


def _is_client(roles, name) -> bool:
    return roles.get(name, {}).get("role") in CLIENT_SIDE


def detect_client_pending(msgs: list[Msg], roles: dict, tasks, links: dict, as_of: Optional[datetime] = None):
    as_of = as_of or (msgs[-1].ts if msgs else datetime.utcnow())
    by_task = {t.id: t for t in tasks}
    items: list[dict] = []
    client_names = [n for n in roles if _is_client(roles, n)]

    for m in msgs:
        s = signals(m.text)
        is_dep = s["client_wait"] or (m.category == "CLIENT_PENDING" and m.cat_conf >= 0.5 and not s["approval"])
        if not is_dep and client_names and m.sender and not _is_client(roles, m.sender) and not s["approval"]:
            named = find_people(m.text, client_names)   # "Mr Kapoor still hasn't sent the logo" / "Amar ji please send the keys"
            if named and (NAMED_NEG.search(m.text) or (NAMED_REQUEST.search(m.text) and client_pending_type(m.text) != "OTHER")):
                is_dep = True
        if is_dep and m.sender and not _is_client(roles, m.sender):
            typ = client_pending_type(m.text)
            lk = links.get(m.id)
            task = by_task.get(lk["task_id"]) if lk else None
            own = topic_set(m.text, extra_stop=("client", "pending", "waiting"))
            topic = (task.topic | own) if task else own   # the linked task's words AND what this message asked for ("keys")
            title_base = task.title if task else " ".join(tokens(re.sub(r"client|pending|waiting|confirmation|approved?|yet", "", m.text, flags=re.I))[:5]) or "client input"
            op = next((i for i in items if i["status"] == "OPEN" and i["type"] == typ and topic_overlap(i["_topic"], topic) >= 0.5), None)
            if op:
                op["source_message_ids"].append(m.id)
                continue
            conf = 0.6 + (0.2 if s["client_wait"] else 0) + (0.1 if m.category == "CLIENT_PENDING" else 0)
            items.append({
                "id": "cp_" + hashlib.sha1(m.id.encode()).hexdigest()[:10], "type": typ,
                "title": f"{typ.title().replace('_', ' ')}: {title_base}"[:140], "_topic": topic,
                "task_id": task.id if task else None, "requested_by": m.sender, "requested_at": m.ts,
                "waiting_since": m.ts, "status": "OPEN", "resolved_at": None, "resolution_message_id": None,
                "responsible": "CLIENT", "weight": task_weight(topic, m.text), "confidence": round(min(conf, 0.95), 2),
                "source_message_ids": [m.id], "model_version": ENGINE_VERSION})
            continue
        # ---- resolution ----------------------------------------------------
        open_items = [i for i in items if i["status"] == "OPEN" and i["waiting_since"] < m.ts]
        if not open_items or not m.sender:
            continue
        from_client = _is_client(roles, m.sender)
        about_client = bool(re.search(r"\bclient\b|\bclient ne\b", norm(m.text)))
        if not (from_client or about_client):
            continue
        mt = topic_set(m.text, extra_stop=("client",))
        for it in open_items:
            ov = topic_overlap(it["_topic"], mt)
            same_type_only = len([i for i in open_items if i["type"] == it["type"]]) == 1
            t = it["type"]
            resolves = False
            if t in ("APPROVAL", "UAT", "FEEDBACK"):
                resolves = (s["approval"] or s["reject"] or (t == "FEEDBACK" and from_client and len(m.text) > 15)) and (ov >= 0.3 or same_type_only)
            elif t in ("REQUIREMENT", "OTHER"):   # an approval of something else must not close an unrelated open item
                resolves = (s["approval"] or s["reject"] or bool(PROVIDED.search(m.text))) and ov >= 0.3
            elif t in ("CREDENTIALS", "CONTENT"):
                generic = not (mt - {"attach", "attached", "share", "shared", "sent", "send", "sending", "email", "mail", "mailed", "bheja", "diya", "bhej"})
                resolves = bool(PROVIDED.search(m.text)) and (ov >= 0.2 or (same_type_only and generic))   # "sent." closes it; "Fee structure attached" does not
            elif t == "PAYMENT":
                resolves = bool(PAID.search(m.text))
            if not resolves and from_client and PROVIDED.search(m.text) and ov >= 0.3 and t not in ("PAYMENT",):
                resolves = True   # the client supplied what was asked ("Fee structure attached") whatever the item type
            if resolves:
                it.update(status="RESOLVED", resolved_at=m.ts, resolution_message_id=m.id)
                it["source_message_ids"].append(m.id)

    for it in items:
        end = it["resolved_at"] or as_of
        it["age_days"] = round(max(0.0, (end - it["waiting_since"]).total_seconds() / 86400), 2)
        base = 2 if it["weight"] >= 5 else 1 if it["weight"] >= 3 else 0
        lvl = min(3, base + (1 if it["age_days"] > 5 and it["status"] == "OPEN" else 0))
        it["impact"] = LEVELS[lvl]
        it["priority"] = LEVELS[min(3, max(1, lvl))]
        it.pop("_topic")
    return items, response_stats(msgs, roles, as_of)


def response_stats(msgs: list[Msg], roles: dict, as_of: datetime) -> dict:
    """Pair a team REQUEST with the first following client message (<=48h, no other client message between)."""
    deltas, pending_req = [], None
    last_client = None
    for m in msgs:
        if not m.sender:
            continue
        if _is_client(roles, m.sender):
            last_client = m.ts
            if pending_req is not None:
                d = (m.ts - pending_req).total_seconds() / 3600
                if d <= 48:
                    deltas.append(d)
                pending_req = None
        elif REQUEST.search(m.text) and pending_req is None:
            s = signals(m.text)
            if s["question"] or s["client_wait"] or re.search(r"\b(?:please|kindly|confirm|approve)\b", m.text, re.I):
                if re.search(r"\bclient\b", m.text, re.I) is None or True:
                    pending_req = m.ts
    out = {"pairs": len(deltas), "last_client_message_at": last_client,
           "client_inactive_days": round((as_of - last_client).total_seconds() / 86400, 2) if last_client else None}
    if deltas:
        out.update(avg_hours=round(statistics.mean(deltas), 2), median_hours=round(statistics.median(deltas), 2),
                   min_hours=round(min(deltas), 2), max_hours=round(max(deltas), 2))
    return out
