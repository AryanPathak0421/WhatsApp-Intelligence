"""Deterministic, configurable project health score (0-100).

Components with no data are DROPPED and the remaining weights renormalised (reported
in `unavailable`), instead of inventing a neutral value.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

DEFAULT_WEIGHTS = {"progress": 0.20, "deadline": 0.15, "risk": 0.15, "blocked": 0.10,
                   "client_dependency": 0.15, "bugs": 0.10, "velocity": 0.15}


def status_for(score: float) -> str:
    return "HEALTHY" if score >= 80 else "AT_RISK" if score >= 60 else "CRITICAL" if score >= 40 else "BLOCKED"


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def compute_health(tasks, progress: dict, risk: dict, velocity: dict, as_of: datetime,
                   project_start: Optional[datetime] = None, expected_delivery: Optional[datetime] = None,
                   weights: Optional[dict] = None) -> dict:
    W = {**DEFAULT_WEIGHTS, **(weights or {})}
    live = [t for t in tasks if t["status"] != "CANCELLED"]
    open_t = [t for t in live if t["status"] != "COMPLETED"]
    comp: dict[str, Optional[tuple[float, str]]] = {}

    # progress vs time elapsed (needs a delivery date, otherwise absolute progress)
    p = progress["overall"]
    if p is None:
        comp["progress"] = None
    elif project_start and expected_delivery and expected_delivery > project_start:
        exp = _clamp((as_of - project_start).total_seconds() / (expected_delivery - project_start).total_seconds())
        v = 1.0 if exp == 0 else _clamp((p / 100) / exp)
        comp["progress"] = (v, f"progress {p}% vs {exp * 100:.0f}% of timeline elapsed")
    else:
        comp["progress"] = (p / 100, f"progress {p}% (no delivery date set, absolute value used)")

    # deadline adherence
    ok = late = 0
    for t in live:
        if not (t.get("deadline")):
            continue
        if t["status"] == "COMPLETED" and t.get("completed_at"):
            ok += t["completed_at"] <= t["deadline"]
            late += t["completed_at"] > t["deadline"]
        elif t["status"] != "COMPLETED" and t["deadline"] < as_of:
            late += 1
    comp["deadline"] = (ok / (ok + late), f"{ok} on time, {late} late/overdue") if ok + late else None

    comp["risk"] = (1 - risk["score"] / 100, f"risk score {risk['score']} ({risk['level']})")

    ow = sum(t["weight"] for t in open_t)
    bw = sum(t["weight"] for t in open_t if t["status"] == "BLOCKED")
    comp["blocked"] = (_clamp(1 - 2 * bw / ow), f"blocked weight {bw:g} of open {ow:g}") if ow else None

    cpv = risk["factors"]["client_pending"]["value"]
    comp["client_dependency"] = (1 - cpv, f"client dependency pressure {cpv:.2f}")
    bv = risk["factors"]["bugs"]["value"]
    comp["bugs"] = (1 - bv, f"bug pressure {bv:.2f}")

    wk = velocity["weeks"]
    if len(wk) >= 3 and sum(w["weight"] for w in wk[:-1]) > 0:
        prev_avg = sum(w["weight"] for w in wk[:-1]) / (len(wk) - 1)
        r = wk[-1]["weight"] / prev_avg
        comp["velocity"] = (_clamp(0.5 + 0.5 * (r - 1)), f"last week {wk[-1]['weight']:g} vs avg {prev_avg:.1f}")
    else:
        comp["velocity"] = None

    avail = {k: v for k, v in comp.items() if v is not None}
    wsum = sum(W[k] for k in avail) or 1.0
    components = {}
    score = 0.0
    for k, (val, why) in avail.items():
        eff = W[k] / wsum
        contrib = 100 * eff * val
        score += contrib
        components[k] = {"value": round(val, 3), "weight": round(W[k], 3), "effective_weight": round(eff, 3),
                         "contribution": round(contrib, 1), "reason": why}
    score = round(score, 1)
    status = status_for(score)
    overrides = []
    flags = []
    open_n = len(open_t)
    if open_n and all(t["status"] == "BLOCKED" for t in open_t):
        status = "BLOCKED"
        overrides.append("status forced to BLOCKED: every open task is blocked, nothing can progress")
    elif ow and bw / ow >= 0.5:
        flags.append(f"{100 * bw / ow:.0f}% of open work is blocked")
    return {"score": score, "status": status, "components": components,
            "unavailable": [k for k, v in comp.items() if v is None], "weights": W, "overrides": overrides, "flags": flags,
            "thresholds": "80-100 HEALTHY, 60-79 AT_RISK, 40-59 CRITICAL, 0-39 BLOCKED"}
