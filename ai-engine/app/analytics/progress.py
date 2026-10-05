"""Weighted project progress, sub-progress per domain, explanation ("Why N%?"), velocity.

progress = sum(weight_i * credit_i) / sum(weight_i) * 100   (cancelled tasks excluded)
Credits are configurable. Default is STRICT (only COMPLETED counts) because partial credit
for "in progress" is an assumption, not evidence.
"""
from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

DEFAULT_CREDITS = {"COMPLETED": 1.0, "IN_PROGRESS": 0.0, "BLOCKED": 0.0, "TODO": 0.0}
DOMAINS = ["DEVELOPMENT", "DESIGN", "TESTING", "DEPLOYMENT", "DOCUMENTATION"]


def _live(tasks):
    return [t for t in tasks if t["status"] != "CANCELLED"]


def _pct(num, den) -> Optional[float]:
    return round(100 * num / den, 1) if den else None


def _signals(t) -> set:
    return {e["signal"] for e in t.get("evidence", [])}


def compute_progress(tasks: list[dict], client_pending: Optional[list[dict]] = None,
                     credits: Optional[dict] = None) -> dict:
    cr = {**DEFAULT_CREDITS, **(credits or {})}
    live = _live(tasks)
    total_w = sum(t["weight"] for t in live)
    done_w = sum(t["weight"] * cr.get(t["status"], 0.0) for t in live)
    overall = _pct(done_w, total_w)

    by_domain = {}
    for d in DOMAINS:
        ts = [t for t in live if t["domain"] == d]
        by_domain[d] = _pct(sum(t["weight"] * cr.get(t["status"], 0.0) for t in ts), sum(t["weight"] for t in ts))

    dev = [t for t in live if t["domain"] == "DEVELOPMENT"]
    dev_w = sum(t["weight"] for t in dev)
    tested_w = sum(t["weight"] for t in dev if t["status"] == "COMPLETED" and "test_pass" in _signals(t))
    testing_tasks = [t for t in live if t["domain"] == "TESTING"]
    t_den = dev_w + sum(t["weight"] for t in testing_tasks)
    t_num = tested_w + sum(t["weight"] for t in testing_tasks if t["status"] == "COMPLETED")
    testing = _pct(t_num, t_den)

    dep_domain = [t for t in live if t["domain"] == "DEPLOYMENT"]
    dep_ev = [t for t in live if t["domain"] != "DEPLOYMENT" and "deploy" in _signals(t) and t["status"] == "COMPLETED"]
    dep_den = total_w
    deployment = _pct(sum(t["weight"] for t in dep_ev) + sum(t["weight"] for t in dep_domain if t["status"] == "COMPLETED"), dep_den) \
        if (dep_ev or dep_domain) else None

    approval = None
    if client_pending is not None:
        items = [c for c in client_pending if c["type"] in ("APPROVAL", "UAT", "FEEDBACK")]
        approval = _pct(sum(1 for c in items if c["status"] == "RESOLVED"), len(items))

    contributions = sorted(
        ({"task_id": t["id"], "title": t["title"], "status": t["status"], "weight": t["weight"],
          "credit": cr.get(t["status"], 0.0), "points": round(t["weight"] * cr.get(t["status"], 0.0), 2),
          "share_of_project_pct": _pct(t["weight"], total_w), "assigned_to": t["assigned_to"],
          "needs_review": t["needs_review"], "evidence_message_ids": t["evidence_message_ids"]} for t in live),
        key=lambda x: (-x["points"], -x["weight"]))
    holding_back = sorted((c for c in contributions if c["credit"] < 1.0), key=lambda x: -x["weight"])[:10]
    counts = defaultdict(int)
    for t in tasks:
        counts[t["status"]] += 1
    warnings = []
    if not live:
        warnings.append("No tasks were extracted; progress cannot be computed.")
    n_rev = sum(1 for t in live if t["status"] == "COMPLETED" and t["needs_review"])
    if n_rev:
        warnings.append(f"{n_rev} completed task(s) are flagged for review; progress may be overstated.")
    if live and total_w / len(live) == 2.0 and all(t["weight"] == 2.0 for t in live):
        warnings.append("All tasks use the default weight; set weights manually for a more accurate percentage.")
    reliability = round(sum(1 for t in live if not t["needs_review"]) / len(live), 2) if live else 0.0
    return {
        "overall": overall, "development": by_domain["DEVELOPMENT"], "design": by_domain["DESIGN"],
        "testing": testing, "deployment": deployment, "client_approval": approval,
        "documentation": by_domain["DOCUMENTATION"],
        "explanation": {
            "formula": "sum(weight x credit) / sum(weight) x 100, cancelled tasks excluded",
            "credits": cr, "completed_weight": round(done_w, 2), "total_weight": round(total_w, 2),
            "task_counts": dict(counts), "task_contributions": contributions, "holding_back": holding_back,
            "reliability": reliability, "warnings": warnings,
            "notes": "A sub-progress of null means there is no evidence for that area (not zero)."},
    }


def progress_timeline(tasks: list[dict], start: datetime, end: datetime, credits: Optional[dict] = None) -> list[dict]:
    """Progress as it would have been at the end of each day (tasks existing by then). O((T + D) log T)."""
    cr = {**DEFAULT_CREDITS, **(credits or {})}
    live = _live(tasks)
    created = sorted((t.get("created_at") or datetime.min, t["weight"]) for t in live)     # undated tasks count from the start
    c_times = [c[0] for c in created]
    c_cum = [0.0]
    for _, w in created:
        c_cum.append(c_cum[-1] + w)
    finished = sorted((t["completed_at"], t["weight"] * cr["COMPLETED"]) for t in live if t["status"] == "COMPLETED" and t.get("completed_at"))
    f_times = [f[0] for f in finished]
    f_cum = [0.0]
    for _, w in finished:
        f_cum.append(f_cum[-1] + w)
    out, day = [], datetime(start.year, start.month, start.day)
    while day <= end:
        d_end = day + timedelta(days=1)
        total = c_cum[bisect_left(c_times, d_end)]          # created strictly before the end of the day
        done = f_cum[bisect_left(f_times, d_end)]
        out.append({"date": day.date().isoformat(), "progress": _pct(done, total), "total_weight": round(total, 1)})
        day = d_end
    for i, p in enumerate(out):
        prev = out[i - 1]["progress"] if i else None
        p["delta"] = round(p["progress"] - prev, 1) if (prev is not None and p["progress"] is not None) else None
    return out


def velocity(tasks: list[dict], start: datetime, end: datetime) -> dict:
    """Tasks (and weight) completed per 7-day window counted back from `end`."""
    done = [t for t in tasks if t["status"] == "COMPLETED" and t.get("completed_at")]
    n_weeks = max(1, int((end - start).total_seconds() // (7 * 86400)) + 1)
    weeks = []
    for i in range(n_weeks):
        w_end = end - timedelta(days=7 * i)
        w_start = w_end - timedelta(days=7)
        inside = [t for t in done if w_start < t["completed_at"] <= w_end]
        weeks.append({"week_ending": w_end.date().isoformat(), "tasks": len(inside),
                      "weight": round(sum(t["weight"] for t in inside), 1)})
    weeks.reverse()
    trend = None
    if len(weeks) >= 3:
        half = len(weeks) // 2
        a = sum(w["weight"] for w in weeks[:half]) / half
        b = sum(w["weight"] for w in weeks[-half:]) / half
        trend = "UP" if b > a * 1.15 else "DOWN" if b < a * 0.85 else "FLAT"
    return {"weeks": weeks, "trend": trend, "complete_weeks": n_weeks}
