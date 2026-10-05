"""Daily / weekly / full A-to-Z report builders (JSON, evidence ids preserved)."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
from typing import Optional

from app.summarization.executive import build_summary
from app.summarization.extractive import summarize_messages


def _d(x) -> Optional[date]:
    return x.date() if isinstance(x, datetime) else x


def _same(ts, day: date) -> bool:
    return ts is not None and _d(ts) == day


def _tl_progress(result, day: date) -> dict:
    row = next((r for r in result["progress_timeline"] if r["date"] == day.isoformat()), None)
    return {"progress": row["progress"] if row else None, "delta": row["delta"] if row else None}


def daily_report(result: dict, msgs, day: date, embedder=None) -> dict:
    tasks = result["tasks"]
    in_day = [m for m in msgs if _same(m.ts, day)]
    completed = [t for t in tasks if t["status"] == "COMPLETED" and _same(t["completed_at"], day)]
    new_tasks = [t for t in tasks if _same(t["created_at"], day)]
    opened = [c for c in result["client_pending"] if _same(c["waiting_since"], day)]
    resolved = [c for c in result["client_pending"] if _same(c["resolved_at"], day)]
    blocked = [t for t in tasks if any(tr["status"] == "BLOCKED" and any(_same(m.ts, day) for m in msgs if m.id == tr["message_id"])
                                       for tr in t["status_trace"])]
    fixed = [b for b in result["bugs"] if any(h["status"] == "FIXED" and _same(h["at"], day) for h in b["history"])]
    reported = [b for b in result["bugs"] if _same(b["reported_at"], day)]
    decisions = [d for d in result["decisions"] if _same(d["decided_at"], day)]
    tp = _tl_progress(result, day)
    ref = lambda ts: [{"id": t["id"], "title": t["title"], "assigned_to": t["assigned_to"], "evidence_message_ids": t["evidence_message_ids"]} for t in ts]  # noqa: E731
    return {
        "date": day.isoformat(), "messages": len(in_day),
        "progress": tp["progress"], "progress_change": tp["delta"],
        "completed": ref(completed), "new_tasks": ref(new_tasks), "blocked": ref(blocked),
        "client_pending_opened": [{"id": c["id"], "title": c["title"], "source_message_ids": c["source_message_ids"]} for c in opened],
        "client_pending_resolved": [{"id": c["id"], "title": c["title"]} for c in resolved],
        "bugs_reported": len(reported), "bugs_fixed": len(fixed),
        "decisions": [{"title": d["title"], "decided_by": d["decided_by"], "source_message_ids": d["source_message_ids"]} for d in decisions],
        "open_risks": [{"title": r["title"], "severity": r["severity"]} for r in result["risk"]["risks"][:5]],
        "key_messages": summarize_messages(in_day, k=5, embedder=embedder),
        "counts": {"completed": len(completed), "new_tasks": len(new_tasks), "client_pending": len(opened), "blocked": len(blocked),
                   "decisions": len(decisions), "risks": len(result["risk"]["risks"])},
    }


def end_prog_known(series) -> bool:
    return any(r["progress"] is not None for r in series)


def week_bounds(day: date) -> tuple[date, date]:
    start = day - timedelta(days=day.weekday())
    return start, start + timedelta(days=6)


def weekly_report(result: dict, msgs, day: date, embedder=None) -> dict:
    start, end = week_bounds(day)
    prev_start = start - timedelta(days=7)
    days = [start + timedelta(days=i) for i in range(7)]
    series = [{"date": d.isoformat(), **_tl_progress(result, d), "messages": sum(1 for m in msgs if _same(m.ts, d)),
               "completed": sum(1 for t in result["tasks"] if t["status"] == "COMPLETED" and _same(t["completed_at"], d))} for d in days]

    def block(s, e):
        rng = lambda ts: ts is not None and s <= _d(ts) <= e  # noqa: E731
        return {"completed": sum(1 for t in result["tasks"] if t["status"] == "COMPLETED" and rng(t["completed_at"])),
                "new_tasks": sum(1 for t in result["tasks"] if rng(t["created_at"])),
                "messages": sum(1 for m in msgs if rng(m.ts)),
                "client_pending_opened": sum(1 for c in result["client_pending"] if rng(c["waiting_since"])),
                "client_pending_resolved": sum(1 for c in result["client_pending"] if rng(c["resolved_at"])),
                "bugs_fixed": sum(1 for b in result["bugs"] if any(h["status"] == "FIXED" and rng(h["at"]) for h in b["history"])),
                "weight_completed": round(sum(t["weight"] for t in result["tasks"] if t["status"] == "COMPLETED" and rng(t["completed_at"])), 1)}

    ps = [r["progress"] for r in series if r["progress"] is not None]
    start_prog = _tl_progress(result, start - timedelta(days=1))["progress"]
    if start_prog is None and end_prog_known(series):
        start_prog = 0.0  # week began before the first task existed
    end_prog = ps[-1] if ps else None
    this, last = block(start, end), block(prev_start, start - timedelta(days=1))
    return {"week_start": start.isoformat(), "week_end": end.isoformat(), "days": series,
            "progress_start": start_prog, "progress_end": end_prog,
            "progress_change": round(end_prog - start_prog, 1) if (end_prog is not None and start_prog is not None) else None,
            "this_week": this, "previous_week": last,
            "comparison": {k: this[k] - last[k] for k in this},
            "key_messages": summarize_messages(msgs, k=6, embedder=embedder,
                                               date_from=datetime.combine(start, datetime.min.time()),
                                               date_to=datetime.combine(end, datetime.max.time()))}


def build_timeline(result: dict, msgs) -> list[dict]:
    """Project timeline from actual evidence (first message, completions, approvals, deploys, decisions, blockers, changes)."""
    ev = []
    if msgs:
        ev.append({"at": msgs[0].ts, "type": "START", "title": "Project discussion started", "source_message_ids": [msgs[0].id]})
    for t in result["tasks"]:
        ev.append({"at": t["created_at"], "type": "TASK_CREATED", "title": f"Task created: {t['title']} ({t['assigned_to'] or 'unassigned'})",
                   "source_message_ids": [t["source_message_id"]]})
        if t["status"] == "COMPLETED" and t["completed_at"]:
            ev.append({"at": t["completed_at"], "type": "COMPLETED", "title": f"Completed: {t['title']}",
                       "source_message_ids": t["evidence_message_ids"][-2:]})
        for e in t["evidence"]:
            if e["signal"] == "deploy" and t["status"] == "COMPLETED":
                ev.append({"at": t["completed_at"] or t["created_at"], "type": "DEPLOYMENT", "title": f"Deployed: {t['title']}",
                           "source_message_ids": [e["message_id"]]})
                break
    for c in result["client_pending"]:
        ev.append({"at": c["waiting_since"], "type": "CLIENT_PENDING", "title": f"Client pending: {c['title']}", "source_message_ids": c["source_message_ids"][:1]})
        if c["resolved_at"]:
            ev.append({"at": c["resolved_at"], "type": "CLIENT_RESOLVED", "title": f"Client responded: {c['title']}",
                       "source_message_ids": [c["resolution_message_id"]]})
    for d in result["decisions"]:
        ev.append({"at": d["decided_at"], "type": "DECISION", "title": f"Decision: {d['title']}", "source_message_ids": d["source_message_ids"]})
    for c in result["requirement_changes"]:
        ev.append({"at": c["changed_at"], "type": "REQUIREMENT_CHANGE", "title": f"Requirement change: {c['key']} {c['old_value'] or '?'} -> {c['new_value']}",
                   "source_message_ids": c["source_message_ids"]})
    for m in result["meetings"]:
        ev.append({"at": m["mentioned_at"], "type": "MEETING", "title": f"Meeting: {m['title']}", "source_message_ids": m["source_message_ids"]})
    # de-duplicate identical (type,title)
    seen, out = set(), []
    for e in sorted(ev, key=lambda e: e["at"]):
        k = (e["type"], e["title"])
        if k not in seen:
            seen.add(k)
            out.append(e)
    return out


def full_report(result: dict, msgs, meta: Optional[dict] = None, embedder=None) -> dict:
    meta = meta or {}
    as_of = result["as_of"]
    tasks = result["tasks"]
    by = lambda st: [t for t in tasks if t["status"] == st]  # noqa: E731
    overdue = [t for t in tasks if t["status"] not in ("COMPLETED", "CANCELLED") and t["deadline"] and t["deadline"] < as_of]
    open_cp = [c for c in result["client_pending"] if c["status"] == "OPEN"]
    sales_names = {s["person"] for s in result["sales"]}
    P = result["progress"]
    areas = sorted(((k, P[k]) for k in ("development", "design", "testing", "deployment", "client_approval", "documentation")
                    if P.get(k) is not None), key=lambda x: x[1])
    summary = build_summary(result)
    recs, seen = [], set()
    for r in result["risk"]["risks"]:
        if r["recommended_action"] and r["recommended_action"] not in seen:
            seen.add(r["recommended_action"])
            recs.append({"recommendation": r["recommended_action"], "because": r["title"], "source_message_ids": r["source_message_ids"][:3]})
    senders = Counter(m.sender for m in msgs if m.sender)
    return {
        "meta": {"company": meta.get("company"), "project": meta.get("name"), "client": meta.get("client"),
                 "reporting_period": [msgs[0].ts if msgs else None, as_of], "generated_at": meta.get("generated_at") or as_of,
                 "engine_version": result["engine_version"]},
        "1_executive_summary": summary,
        "2_project_overview": {"name": meta.get("name"), "client": meta.get("client"), "project_manager": meta.get("manager"),
                               "start_date": meta.get("start_date") or (msgs[0].ts if msgs else None),
                               "expected_delivery": meta.get("expected_delivery"), "messages_analysed": len(msgs),
                               "participants": len(senders), "tasks_extracted": len(tasks)},
        "3_progress": P, "4_health": result["health"],
        "5_team": [{"name": n, **r, "messages": senders.get(n, 0)} for n, r in result["roles"].items()],
        "6_developer_contribution": result["contribution"], "7_sales_activity": result["sales"],
        "8_client_activity": {"response_time": result["client_response_time"], "open_items": len(open_cp),
                              "resolved_items": sum(1 for c in result["client_pending"] if c["status"] == "RESOLVED")},
        "9_completed_work": by("COMPLETED"), "10_in_progress_work": by("IN_PROGRESS"), "11_pending_work": by("TODO"),
        "12_blocked_work": by("BLOCKED"), "13_client_pending": result["client_pending"],
        "14_sales_pending": [c for c in open_cp if c["requested_by"] in sales_names],
        "15_bugs": result["bugs"], "16_requirements": result["requirements"], "17_requirement_changes": result["requirement_changes"],
        "18_decisions": result["decisions"], "19_meetings": result["meetings"],
        "20_deadlines": sorted((t for t in tasks if t["deadline"]), key=lambda t: t["deadline"]),
        "21_overdue_tasks": overdue, "22_risks": result["risk"], "23_communication_analytics": result["communication"],
        "23b_conflicts": result["conflicts"], "24_timeline": build_timeline(result, msgs),
        "25_team_performance": [{k: c[k] for k in ("person", "role", "assigned", "completed", "overdue", "weighted_completion_pct",
                                                  "on_time_pct", "score", "low_sample")} for c in result["contribution"]],
        "26_bottlenecks": {"lowest_progress_areas": areas[:2], "blocked_tasks": [t["title"] for t in by("BLOCKED")],
                           "client_waits": [{"title": c["title"], "age_days": c["age_days"]} for c in sorted(open_cp, key=lambda c: -c["age_days"])[:5]],
                           "overdue": [t["title"] for t in overdue]},
        "27_recommendations": recs, "28_next_actions": result["next_actions"],
        "weekly": weekly_report(result, msgs, as_of.date(), embedder), "daily": daily_report(result, msgs, as_of.date(), embedder),
        "key_messages": summarize_messages(msgs, k=8, embedder=embedder),
    }
