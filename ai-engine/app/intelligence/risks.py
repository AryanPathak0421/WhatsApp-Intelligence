"""Explainable risk engine: weighted factors -> score 0-100 + individual risk records."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Optional

from app.intelligence.tasks import task_weight
from app.intelligence.types import ENGINE_VERSION, Msg

DEFAULT_WEIGHTS = {"deadline": 0.20, "blocked": 0.15, "client_pending": 0.15, "client_inactivity": 0.10,
                   "requirement_churn": 0.10, "bugs": 0.10, "communication_drop": 0.10, "backlog": 0.10}


def level(score: float) -> str:
    return "LOW" if score < 30 else "MEDIUM" if score < 55 else "HIGH" if score < 75 else "CRITICAL"


def _w(t) -> float:
    return task_weight(t.topic, t.title)


def detect_risks(msgs, tasks, client_items, bugs, req_changes, conflicts, response, as_of: Optional[datetime] = None,
                 weights: Optional[dict] = None) -> dict:
    as_of = as_of or (msgs[-1].ts if msgs else datetime.utcnow())
    W = {**DEFAULT_WEIGHTS, **(weights or {})}
    live = [t for t in tasks if t.status != "CANCELLED"]
    open_t = [t for t in live if t.status != "COMPLETED"]
    tot_open_w = sum(_w(t) for t in open_t) or 1.0
    tot_w = sum(_w(t) for t in live) or 1.0
    risks: list[dict] = []

    def add(title, sev, desc, action, ids, task=None, score=None, kind=""):
        risks.append({"id": "rk_" + hashlib.sha1((kind + title + "".join(ids)).encode()).hexdigest()[:10],
                      "title": title, "severity": sev, "description": desc, "recommended_action": action,
                      "detected_at": as_of, "related_task": task.id if task else None,
                      "source_message_ids": ids, "confidence": 0.8, "model_version": ENGINE_VERSION})

    overdue = [t for t in open_t if t.deadline and t.deadline.when and t.deadline.when < as_of]
    for t in overdue:
        days = (as_of - t.deadline.when).total_seconds() / 86400
        sev = "HIGH" if _w(t) >= 3 or days > 3 else "MEDIUM"
        add(f"Task overdue: {t.title}", sev, f"Deadline '{t.deadline.text}' passed {days:.1f} days ago; status {t.status}.",
            f"Ask {t.assignee or 'owner'} for an updated ETA.", t.source_ids(), t, kind="overdue")
    soon = [t for t in open_t if t.deadline and t.deadline.when and as_of <= t.deadline.when <= as_of + timedelta(days=2)]
    for t in soon:
        add(f"Deadline approaching: {t.title}", "MEDIUM", f"Due {t.deadline.when:%d %b}; status {t.status}.",
            "Confirm it will land on time.", t.source_ids(), t, kind="soon")
    blocked = [t for t in open_t if t.status == "BLOCKED"]
    blocked_days = {}
    for t in blocked:
        since = next((tr for tr in reversed(t.status_trace) if tr["status"] == "BLOCKED"), None)
        t_since = next((e for e in t.evidence if since and e.message_id == since["message_id"]), None)
        d = (as_of - (t.last_touch or t.created_at)).total_seconds() / 86400
        blocked_days[t.id] = d
        add(f"Blocked: {t.title}", "HIGH" if d > 2 or _w(t) >= 5 else "MEDIUM",
            f"Blocked by {t.external_dependency or 'a dependency'} (~{d:.1f} days since last update).",
            "Resolve the dependency or escalate." if not (t.external_dependency or "").startswith("CLIENT") else "Follow up with the client.",
            t.source_ids(), t, kind="blocked")
    open_cp = [c for c in client_items if c["status"] == "OPEN"]
    for c in open_cp:
        if c["age_days"] >= 2:
            add(f"Client pending: {c['title']}", "HIGH" if c["age_days"] > 5 or c["impact"] in ("HIGH", "CRITICAL") else "MEDIUM",
                f"Waiting {c['age_days']:.1f} days on the client.", "Follow up with the client today.",
                c["source_message_ids"], kind="cp")
    inactive = response.get("client_inactive_days")
    if inactive is not None and inactive >= 3 and open_cp:
        add("Client not responding", "HIGH" if inactive >= 5 else "MEDIUM",
            f"No client message for {inactive:.1f} days while {len(open_cp)} item(s) wait on them.",
            "Escalate through sales / project manager.", sum((c["source_message_ids"][:1] for c in open_cp), []), kind="inactive")
    recent_changes = [c for c in req_changes if as_of - c["changed_at"] <= timedelta(days=14)]
    if len(recent_changes) >= 3:
        add("Requirements changing repeatedly", "HIGH" if len(recent_changes) >= 5 else "MEDIUM",
            f"{len(recent_changes)} requirement changes in 14 days.", "Freeze scope / agree a change-request process.",
            sum((c["source_message_ids"] for c in recent_changes), []), kind="churn")
    open_bugs = [b for b in bugs if b["status"] in ("OPEN", "INVESTIGATING", "IN_PROGRESS", "REOPENED")]
    if len(open_bugs) >= 5:
        add("Many unresolved bugs", "HIGH" if len(open_bugs) >= 8 else "MEDIUM", f"{len(open_bugs)} open bugs.",
            "Schedule a bug-fix sprint.", sum((b["source_message_ids"][:1] for b in open_bugs), []), kind="bugs")
    for cf in conflicts:
        if cf["severity"] == "HIGH":
            add(f"Conflicting statements: {cf['topic']}", "MEDIUM", "Team members disagree on status; needs verification.",
                "Verify the actual state and correct the record.", cf["source_message_ids"], kind="conflict")
    last_ts = msgs[-1].ts if msgs else as_of
    silent = (as_of - last_ts).total_seconds() / 86400
    recent = sum(1 for m in msgs if as_of - timedelta(days=7) < m.ts <= as_of)
    prev = sum(1 for m in msgs if as_of - timedelta(days=14) < m.ts <= as_of - timedelta(days=7))
    drop = 1.0 if silent >= 5 else (max(0.0, 1 - (recent / prev) / 0.4) if prev >= 10 and recent / prev < 0.4 else 0.0)
    if drop > 0:
        add("Communication drop", "MEDIUM", f"{silent:.0f} days silent / activity {recent} vs {prev} previous week.",
            "Check in with the team.", [msgs[-1].id] if msgs else [], kind="silence")

    ow = sum(_w(t) for t in overdue)
    factors = {
        "deadline": min(1.0, 1.5 * ow / tot_open_w),
        "blocked": min(1.0, 2.0 * sum(_w(t) for t in blocked) / tot_open_w),
        "client_pending": min(1.0, 0.15 * len(open_cp) + 0.04 * max([c["age_days"] for c in open_cp] or [0])),
        "client_inactivity": min(1.0, inactive / 7) if (inactive is not None and open_cp) else 0.0,
        "requirement_churn": min(1.0, len(recent_changes) / 4),
        "bugs": min(1.0, len(open_bugs) / 6),
        "communication_drop": drop,
        "backlog": sum(_w(t) for t in live if t.status == "TODO") / tot_w,
    }
    score = round(100 * sum(W[k] * v for k, v in factors.items()), 1)
    order = {"CRITICAL": 3, "HIGH": 2, "MEDIUM": 1, "LOW": 0}
    risks.sort(key=lambda r: -order[r["severity"]])
    return {"score": score, "level": level(score), "weights": W,
            "factors": {k: {"value": round(v, 3), "weight": W[k], "contribution": round(100 * W[k] * v, 1)}
                        for k, v in factors.items()}, "risks": risks, "model_version": ENGINE_VERSION}
