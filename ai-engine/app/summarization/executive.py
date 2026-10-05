"""Evidence-bound executive summary (no free-text generation).

Each sentence is rendered from a template + a fact computed from the analysis result, and carries the
task / message ids that justify it. `verify_summary` re-derives every number from the result.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

AREAS = [("development", "Development"), ("design", "Design"), ("testing", "Testing"),
         ("deployment", "Deployment"), ("client_approval", "Client approval"), ("documentation", "Documentation")]


def _claim(kind, text, facts, task_ids=(), message_ids=()):
    return {"kind": kind, "text": text, "facts": facts, "task_ids": list(task_ids), "message_ids": list(dict.fromkeys(message_ids))}


def build_summary(result: dict, as_of: Optional[datetime] = None) -> dict:
    as_of = as_of or result["as_of"]
    P, H, tasks = result["progress"], result["health"], result["tasks"]
    claims = []
    if P["overall"] is None:
        claims.append(_claim("progress", "No tasks could be extracted from this chat, so progress cannot be calculated.", {}))
        return _finish(claims)

    ex = P["explanation"]
    claims.append(_claim("progress", f"Project is currently {P['overall']:g}% complete "
                         f"({ex['completed_weight']:g} of {ex['total_weight']:g} weighted work).",
                         {"overall": P["overall"], "completed_weight": ex["completed_weight"], "total_weight": ex["total_weight"]},
                         [c["task_id"] for c in ex["task_contributions"] if c["credit"] >= 1][:20]))
    areas = [(label, P[k]) for k, label in AREAS if P.get(k) is not None]
    if len(areas) >= 2:
        best, worst = max(areas, key=lambda a: a[1]), min(areas, key=lambda a: a[1])
        if best[0] != worst[0]:
            claims.append(_claim("areas", f"{best[0]} is progressing best at {best[1]:g}%; {worst[0]} is currently the main bottleneck at {worst[1]:g}%.",
                                 {"best": best, "worst": worst}))
    claims.append(_claim("health", f"Project health is {H['score']:g}/100 ({H['status'].replace('_', ' ')}).",
                         {"score": H["score"], "status": H["status"]}))

    open_cp = [c for c in result["client_pending"] if c["status"] == "OPEN"]
    if open_cp:
        oldest = max(open_cp, key=lambda c: c["age_days"])
        claims.append(_claim("client_pending", f"There {'is' if len(open_cp) == 1 else 'are'} {len(open_cp)} pending item"
                             f"{'' if len(open_cp) == 1 else 's'} from the client; the oldest ({oldest['title']}) has waited {oldest['age_days']:.0f} days.",
                             {"count": len(open_cp), "oldest_age_days": oldest["age_days"]},
                             [c["task_id"] for c in open_cp if c["task_id"]], sum((c["source_message_ids"][:1] for c in open_cp), [])))
    overdue = [t for t in tasks if t["status"] not in ("COMPLETED", "CANCELLED") and t["deadline"] and t["deadline"] < as_of]
    if overdue:
        names = ", ".join(t["title"] for t in sorted(overdue, key=lambda t: -t["weight"])[:3])
        claims.append(_claim("overdue", f"{len(overdue)} task{'' if len(overdue) == 1 else 's'} {'is' if len(overdue) == 1 else 'are'} overdue ({names}).",
                             {"count": len(overdue)}, [t["id"] for t in overdue], sum((t["evidence_message_ids"][:1] for t in overdue), [])))
    for ins in [i for i in result["insights"] if i["kind"] == "BLOCKER"][:2]:
        claims.append(_claim("blocker", ins["text"][:1].upper() + ins["text"][1:], {}, message_ids=ins["source_message_ids"]))
    if result["requirement_changes"]:
        ch = result["requirement_changes"][-1]
        claims.append(_claim("requirements", f"{len(result['requirement_changes'])} requirement change"
                             f"{'' if len(result['requirement_changes']) == 1 else 's'} detected; latest: {ch['key']} "
                             f"{ch['old_value'] or '?'} -> {ch['new_value']}.", {"count": len(result["requirement_changes"])},
                             message_ids=ch["source_message_ids"]))
    if result["conflicts"]:
        claims.append(_claim("conflicts", f"{len(result['conflicts'])} potential contradiction"
                             f"{'' if len(result['conflicts']) == 1 else 's'} {'needs' if len(result['conflicts']) == 1 else 'need'} verification.", {"count": len(result["conflicts"])},
                             message_ids=sum((c["source_message_ids"] for c in result["conflicts"]), [])))
    risks = result["risk"]["risks"]
    if risks:
        r = risks[0]
        claims.append(_claim("risk", f"Highest project risk: {r['title']} ({r['severity']}).", {"severity": r["severity"]},
                             [r["related_task"]] if r["related_task"] else [], r["source_message_ids"]))
    if result["next_actions"]:
        a = result["next_actions"][0]
        claims.append(_claim("action", f"Recommended action: {a['action']}" + (f" (owner: {a['owner']}, {a['deadline']})." if a["owner"] else f" ({a['deadline']})."),
                             {"priority": a["priority"]}, message_ids=a["source_message_ids"]))
    if ex["reliability"] < 0.8:
        n = sum(1 for t in tasks if t["needs_review"])
        claims.append(_claim("quality", f"{n} extracted task{'' if n == 1 else 's'} need human review; figures may change after correction.",
                             {"needs_review": n, "reliability": ex["reliability"]}))
    return _finish(claims)


def _finish(claims):
    return {"claims": claims, "text": " ".join(c["text"] for c in claims)}


def verify_summary(summary: dict, result: dict) -> list[str]:
    """Return a list of problems (empty = every claim is backed by the result)."""
    problems = []
    task_ids = {t["id"] for t in result["tasks"]}
    msg_ids = set(result.get("message_links", {}))
    for t in result["tasks"]:
        msg_ids |= set(t["evidence_message_ids"])
    for c in result["client_pending"] + result["requirement_changes"] + result["conflicts"] + result["risk"]["risks"]:
        msg_ids |= set(c["source_message_ids"])
    for c in summary["claims"]:
        for tid in c["task_ids"]:
            if tid not in task_ids:
                problems.append(f"{c['kind']}: unknown task id {tid}")
        for mid in c["message_ids"]:
            if mid not in msg_ids:
                problems.append(f"{c['kind']}: unknown message id {mid}")
        f = c["facts"]
        if c["kind"] == "progress" and f and f["overall"] != result["progress"]["overall"]:
            problems.append("progress mismatch")
        if c["kind"] == "health" and f["score"] != result["health"]["score"]:
            problems.append("health mismatch")
        if c["kind"] == "client_pending" and f["count"] != sum(1 for x in result["client_pending"] if x["status"] == "OPEN"):
            problems.append("client pending count mismatch")
        if c["kind"] not in ("progress",) and not (c["task_ids"] or c["message_ids"] or f):
            problems.append(f"{c['kind']}: no evidence")
    return problems
