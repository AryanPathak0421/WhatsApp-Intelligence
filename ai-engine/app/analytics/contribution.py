"""Developer contribution (explainable), sales activity and communication analysis.

Message count is reported as information ONLY and never enters the score.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime
from typing import Optional

from app.intelligence.rules import signals

WEIGHTS = {"weighted_completion": 0.35, "on_time": 0.20, "bug_fixes": 0.15, "deployments": 0.10,
           "commitments": 0.10}
BLOCKED_PENALTY = 0.10  # score is multiplied by (1 - penalty x blocked share of open work); never a positive credit
TEAM_ROLES = {"DEVELOPER", "FRONTEND_DEVELOPER", "BACKEND_DEVELOPER", "FULLSTACK_DEVELOPER", "QA", "DESIGNER"}


def compute_contribution(tasks: list[dict], bugs: list[dict], commitments: list[dict], msgs, roles: dict,
                         as_of: datetime, weights: Optional[dict] = None) -> list[dict]:
    W = {**WEIGHTS, **(weights or {})}
    sender = {m.id: m.sender for m in msgs}
    live = [t for t in tasks if t["status"] != "CANCELLED"]
    people = {t["assigned_to"] for t in live if t["assigned_to"]}
    fixed_by = Counter(sender.get(h["message_id"]) for b in bugs for h in b["history"] if h["status"] == "FIXED")
    deployed_by: Counter = Counter()
    for t in live:
        if t["status"] == "COMPLETED" and t["assigned_to"] and any(e["signal"] == "deploy" for e in t["evidence"]):
            deployed_by[t["assigned_to"]] += t["weight"]
    people |= {p for p in fixed_by if p} | {c["person"] for c in commitments}
    max_fix = max([fixed_by[p] for p in people if p] or [0])
    max_dep = max([deployed_by[p] for p in people if p] or [0])
    msg_count = Counter(m.sender for m in msgs if m.sender)
    tests = Counter(m.sender for m in msgs if m.sender and signals(m.text)["test_pass"])

    out = []
    for p in sorted(x for x in people if x):
        mine = [t for t in live if t["assigned_to"] == p]
        aw = sum(t["weight"] for t in mine)
        cw = sum(t["weight"] for t in mine if t["status"] == "COMPLETED")
        counts = Counter(t["status"] for t in mine)
        overdue = [t for t in mine if t["status"] != "COMPLETED" and t.get("deadline") and t["deadline"] < as_of]
        with_dl = [t for t in mine if t["status"] == "COMPLETED" and t.get("deadline") and t.get("completed_at")]
        on_time = sum(t["completed_at"] <= t["deadline"] for t in with_dl)
        cm = [c for c in commitments if c["person"] == p]
        cm_ok = sum(c["status"] == "FULFILLED" for c in cm)
        cm_den = sum(c["status"] in ("FULFILLED", "MISSED") for c in cm)
        open_w = sum(t["weight"] for t in mine if t["status"] != "COMPLETED")
        blocked_w = sum(t["weight"] for t in mine if t["status"] == "BLOCKED")
        comp = {
            "weighted_completion": (cw / aw, f"{cw:g} of {aw:g} assigned weight completed") if aw else None,
            "on_time": (on_time / len(with_dl), f"{on_time}/{len(with_dl)} completed on or before deadline") if with_dl else None,
            "bug_fixes": (fixed_by[p] / max_fix, f"{fixed_by[p]} bugs fixed (team max {max_fix})") if max_fix else None,
            "deployments": (deployed_by[p] / max_dep, f"{deployed_by[p]:g} deployed weight (team max {max_dep:g})") if max_dep else None,
            "commitments": (cm_ok / cm_den, f"{cm_ok}/{cm_den} commitments fulfilled") if cm_den else None,
        }
        avail = {k: v for k, v in comp.items() if v}
        wsum = sum(W[k] for k in avail) or 1.0
        score, parts = 0.0, {}
        for k, (v, why) in avail.items():
            c = 100 * W[k] / wsum * v
            score += c
            parts[k] = {"value": round(v, 3), "effective_weight": round(W[k] / wsum, 3), "contribution": round(c, 1), "reason": why}
        blocked_share = blocked_w / open_w if open_w else 0.0
        mult = 1 - BLOCKED_PENALTY * blocked_share
        if blocked_share:
            parts["blocked_penalty"] = {"value": round(blocked_share, 3), "multiplier": round(mult, 3),
                                        "reason": f"{blocked_w:g} of {open_w:g} open weight blocked (often external)"}
        score *= mult
        out.append({
            "person": p, "role": roles.get(p, {}).get("role"), "assigned": len(mine), "completed": counts["COMPLETED"],
            "in_progress": counts["IN_PROGRESS"], "pending": counts["TODO"], "blocked": counts["BLOCKED"],
            "overdue": len(overdue), "completion_pct": round(100 * counts["COMPLETED"] / len(mine), 1) if mine else None,
            "weighted_completion_pct": round(100 * cw / aw, 1) if aw else None,
            "on_time_pct": round(100 * on_time / len(with_dl), 1) if with_dl else None,
            "bugs_fixed": fixed_by[p], "deployed_weight": deployed_by[p], "tests_verified": tests[p],
            "commitments_fulfilled": cm_ok, "commitments_missed": sum(c["status"] == "MISSED" for c in cm),
            "score": round(score, 1) if avail else None, "components": parts,
            "unavailable_components": [k for k, v in comp.items() if v is None],
            "low_sample": len(mine) < 3,
            "info_only": {"message_count": msg_count[p], "note": "message count is NOT part of the score"},
            "task_ids": [t["id"] for t in mine]})
    out.sort(key=lambda x: -(x["score"] or 0))
    return out


def sales_activity(msgs, roles: dict, client_pending: list[dict]) -> list[dict]:
    rows = []
    for name, r in roles.items():
        if r["role"] != "SALES":
            continue
        mine = [m for m in msgs if m.sender == name]
        fu = [m for m in mine if signals(m.text)["client_wait"] or re.search(r"follow(?:ed)?[- ]?up|reminder", m.text, re.I)]
        pend = [c for c in client_pending if c["requested_by"] == name and c["status"] == "OPEN"]
        rows.append({
            "person": name, "client_follow_ups": len(fu),
            "follow_ups_pending": len(pend), "follow_ups_resolved": sum(1 for c in client_pending if c["requested_by"] == name and c["status"] == "RESOLVED"),
            "payment_discussions": sum(1 for m in mine if signals(m.text)["payment"]),
            "proposals": sum(1 for m in mine if re.search(r"proposal|quote|quotation|estimate", m.text, re.I)),
            "escalations": sum(1 for m in mine if re.search(r"escalat", m.text, re.I)),
            "pending_item_ids": [c["id"] for c in pend],
            "source_message_ids": [m.id for m in fu][:50]})
    return rows


def communication(msgs, tasks: list[dict], as_of: datetime) -> dict:
    per_sender = Counter(m.sender for m in msgs if m.sender)
    per_day: Counter = Counter(m.ts.date().isoformat() for m in msgs)
    received = Counter(t["assigned_to"] for t in tasks if t["assigned_to"])
    overdue = Counter(t["assigned_to"] for t in tasks if t["assigned_to"] and t["status"] not in ("COMPLETED", "CANCELLED")
                      and t.get("deadline") and t["deadline"] < as_of)
    resolved = Counter(t["assigned_to"] for t in tasks if t["assigned_to"] and t["status"] == "COMPLETED")
    return {"messages_per_sender": dict(per_sender.most_common()), "messages_per_day": dict(sorted(per_day.items())),
            "tasks_received": dict(received.most_common()), "tasks_resolved": dict(resolved.most_common()),
            "overdue_by_person": dict(overdue.most_common()),
            "note": "Message volume is not performance; use contribution scores for work output."}
