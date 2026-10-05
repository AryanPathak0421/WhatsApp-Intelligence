"""Hierarchical daily -> weekly -> monthly summaries, built from the structured analysis (never by feeding the whole chat to a model).

Each DAY is a set of facts (counts + items with their source message ids). A WEEK merges its days, a MONTH merges its weeks, so the long
horizons are assembled from verified lower levels instead of re-reading raw text. Every highlight carries source_message_ids; the text is a
template over those facts, so nothing is stated that the evidence does not contain. Counts are arithmetic. No generative model is involved.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Optional

from app.intelligence.topics import topic_set
from app.intelligence.types import Msg

CAP = 6                       # items listed per category in a summary text


def _d(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%d")


def _week_key(ts: datetime) -> str:
    y, w, _ = ts.isocalendar()
    return f"{y}-W{w:02d}"


def _month_key(ts: datetime) -> str:
    return ts.strftime("%Y-%m")


def _empty() -> dict:
    return {"messages": 0, "senders": Counter(), "topics": Counter(), "items": defaultdict(list), "negative": 0, "frustrated": 0, "urgent": 0}


def _item(kind: str, text: str, ids, **extra) -> dict:
    return {"kind": kind, "text": text, "source_message_ids": list(ids), **extra}


def _collect_daily(result: dict, msgs: list[Msg]) -> dict[str, dict]:
    days: dict[str, dict] = defaultdict(_empty)
    for m in msgs:
        if not m.text:
            continue
        f = days[_d(m.ts)]
        f["messages"] += 1
        if m.sender:
            f["senders"][m.sender] += 1
        for g in topic_set(m.text):
            if g.startswith("@"):
                f["topics"][g[1:]] += 1
    for t in result.get("tasks", []):
        if t.get("created_at"):
            days[_d(t["created_at"])]["items"]["task_created"].append(_item("task_created", t["title"], t["evidence_message_ids"][:3], task_id=t["id"], assignee=t.get("assigned_to")))
        if t.get("completed_at") and t["status"] == "COMPLETED":
            days[_d(t["completed_at"])]["items"]["task_completed"].append(_item("task_completed", t["title"], t["evidence_message_ids"][-3:], task_id=t["id"], assignee=t.get("assigned_to")))
    for dcs in result.get("decisions", []):
        days[_d(dcs["decided_at"])]["items"]["decision"].append(_item("decision", dcs["title"], dcs["source_message_ids"], by=dcs.get("decided_by")))
    for b in result.get("bugs", []):
        days[_d(b["reported_at"])]["items"]["bug_reported"].append(_item("bug_reported", b["title"], b["source_message_ids"][:2]))
        if b.get("fixed_at"):
            days[_d(b["fixed_at"])]["items"]["bug_fixed"].append(_item("bug_fixed", b["title"], b["source_message_ids"][-2:]))
    for c in result.get("conflicts", []):
        a, b = c["statement_a"], c["statement_b"]
        days[_d(b["at"])]["items"]["conflict"].append(_item("conflict", f"Possible conflict on {c.get('topic', 'a topic')} (needs verification)", [a["message_id"], b["message_id"]]))
    for mt in result.get("meetings", []):
        days[_d(mt["mentioned_at"])]["items"]["meeting"].append(_item("meeting", mt["title"], mt["source_message_ids"]))
    for cp in result.get("client_pending", []):
        days[_d(cp["requested_at"])]["items"]["client_pending_opened"].append(_item("client_pending_opened", cp["title"], cp["source_message_ids"][:2], status=cp["status"]))
    for q in (result.get("qa") or {}).get("items", []):
        if q["status"] in ("UNANSWERED", "POSSIBLY_ANSWERED"):
            days[_d(q["asked_at"])]["items"]["question_open"].append(_item("question_open", q["text"], q["evidence_message_ids"], asked_by=q["asked_by"], status=q["status"]))
    for s in (result.get("sentiment") or {}).get("items", []):
        f = days[_d(s["ts"])]
        f["negative"] += s["label"] == "NEGATIVE"
        f["frustrated"] += bool(s["frustration"])
        f["urgent"] += s["urgency"] > 0
        if s["frustration"] or s["urgency"] >= 1.0:
            f["items"]["attention"].append(_item("attention", "Frustrated or urgent message", [s["message_id"]], sender=s["sender"]))
    return days


def _merge(parts: list[dict]) -> dict:
    out = _empty()
    for p in parts:
        out["messages"] += p["messages"]
        out["senders"].update(p["senders"])
        out["topics"].update(p["topics"])
        for k in ("negative", "frustrated", "urgent"):
            out[k] += p[k]
        for kind, items in p["items"].items():
            seen = {tuple(i["source_message_ids"]) for i in out["items"][kind]}
            out["items"][kind] += [i for i in items if tuple(i["source_message_ids"]) not in seen]
    return out


def _text(label: str, f: dict) -> str:
    it = f["items"]
    bits = [f"{label}: {f['messages']} messages from {len(f['senders'])} participant(s)."]

    def listing(kind, prefix):
        xs = it.get(kind, [])
        if xs:
            shown = "; ".join(x["text"][:70] for x in xs[:CAP])
            bits.append(f"{prefix} ({len(xs)}): {shown}{' ...' if len(xs) > CAP else ''}.")
    listing("task_created", "New tasks")
    listing("task_completed", "Completed")
    listing("decision", "Decisions")
    listing("bug_reported", "Bugs reported")
    listing("bug_fixed", "Bugs fixed")
    listing("conflict", "Possible conflicts")
    listing("meeting", "Meetings")
    listing("client_pending_opened", "Waiting on the client")
    listing("question_open", "Questions without a confirmed answer")
    if f["frustrated"] or f["negative"]:
        bits.append(f"Tone (lexicon baseline): {f['negative']} negative and {f['frustrated']} frustrated message(s).")
    if f["topics"]:
        bits.append("Main topics: " + ", ".join(f"{t} ({n})" for t, n in f["topics"].most_common(4)) + ".")
    return " ".join(bits)


def _finish(kind: str, key: str, start: datetime, end: datetime, f: dict, extra: Optional[dict] = None) -> dict:
    highlights = [i for k in ("decision", "task_completed", "task_created", "bug_reported", "bug_fixed", "conflict", "client_pending_opened", "question_open", "meeting", "attention")
                  for i in f["items"].get(k, [])]
    ids = sorted({m for h in highlights for m in h["source_message_ids"]})
    return {"kind": kind, "key": key, "start": start, "end": end,
            "stats": {"messages": f["messages"], "participants": len(f["senders"]), "top_senders": f["senders"].most_common(3),
                      **{f"n_{k}": len(v) for k, v in sorted(f["items"].items())}, "negative": f["negative"], "frustrated": f["frustrated"], "urgent": f["urgent"]},
            "topics": f["topics"].most_common(5), "highlights": highlights[:60], "evidence_message_ids": ids, "text": _text(f"{kind.title()} {key}", f), **(extra or {})}


def build_periodic(result: dict, msgs: list[Msg], max_days: int = 400) -> dict:
    daily = _collect_daily(result, msgs)
    keys = sorted(daily)[-max_days:]
    weeks: dict[str, list[str]] = defaultdict(list)
    for k in keys:
        weeks[_week_key(datetime.strptime(k, "%Y-%m-%d"))].append(k)
    months: dict[str, list[str]] = defaultdict(list)
    week_facts = {w: _merge([daily[d] for d in ds]) for w, ds in weeks.items()}
    for w, ds in weeks.items():
        months[_month_key(datetime.strptime(ds[0], "%Y-%m-%d"))].append(w)
    out_days = [_finish("daily", k, datetime.strptime(k, "%Y-%m-%d"), datetime.strptime(k, "%Y-%m-%d") + timedelta(days=1), daily[k]) for k in keys]
    out_weeks = [_finish("weekly", w, datetime.strptime(ds[0], "%Y-%m-%d"), datetime.strptime(ds[-1], "%Y-%m-%d") + timedelta(days=1), week_facts[w]) for w, ds in sorted(weeks.items())]
    out_months, prev = [], None
    for mk, ws in sorted(months.items()):
        f = _merge([week_facts[w] for w in ws])
        recurring = [t for t, c in Counter(t for w in ws for t in week_facts[w]["topics"]).items() if c >= 2]
        trend = None
        if prev is not None and prev["messages"]:
            trend = {"messages_vs_previous_month_pct": round(100 * (f["messages"] - prev["messages"]) / prev["messages"], 1),
                     "tasks_completed_delta": len(f["items"].get("task_completed", [])) - len(prev["items"].get("task_completed", []))}
        first = datetime.strptime(weeks_first(weeks, ws), "%Y-%m-%d")
        out_months.append(_finish("monthly", mk, first, first + timedelta(days=31), f, {"recurring_topics": recurring[:6], "trend": trend}))
        prev = f
    return {"daily": out_days, "weekly": out_weeks, "monthly": out_months,
            "method": "hierarchical: day facts -> weeks -> months; templated text over evidence-linked facts; no generative model"}


def weeks_first(weeks: dict, ws: list[str]) -> str:
    return min(weeks[w][0] for w in ws)
