"""Pre-labelling: propose a label for every message so annotators CORRECT instead of labelling from scratch.

    python -m app.annotation.prelabel chat.anon.txt out.batch.json --project hg-enterprises [--role "Person B=CLIENT"] [--double 0.1] [--seed 1]

Proposals come from the rule engine (signals + task linking + roles) and, if one is configured, the production classifier.
They are SUGGESTIONS with an honest confidence: nothing is stored as a human label until an annotator saves it, and the annotator's accept/change decision is recorded
(`model_prediction`) so we can measure how good the proposals really are (`annotation_stats`).

Batch contents (JSON): meta + items. Each item has the message, +-N context messages, the proposal (category, confidence, alternatives, status, assignee, deadline,
task_key, flags), the triage lane (auto_accept / review / annotate), and whether it belongs to the double-annotation sample.
Use ONLY anonymised chats here (app/datasets/anonymize.py).
"""
from __future__ import annotations

import argparse
import json
import random
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.annotation.core import triage
from app.intelligence.pipeline import analyze
from app.intelligence.roles import CLIENT_SIDE, COMPLAINT, REVIEW_REQUEST, PAID, PAY_REQUEST
from app.intelligence.rules import signals
from app.intelligence.temporal import extract_deadline
from app.intelligence.types import ENGINE_VERSION, Msg
from app.labels import CATEGORIES
from app.parsers.whatsapp import WhatsAppParser

CHATTER = re.compile(r"^\W*(?:ok(?:ay|y|h)?|thanks?|thank you|thik(?: hai)?|theek(?: hai)?|sure|yes|no|haan|han|ji|hmm+|done|great|good|nice|welcome|"
                     r"ठीक है|जी|हाँ|हां|ओके|धन्यवाद|शुक्रिया)\W*$", re.I)
# Hinglish / Devanagari cues (plain search, no \w lookarounds: Devanagari matras are not word characters in Python's re)
HI_REQUIREMENT = re.compile(
    r"चाहिए|रहेगा|रहेंगे|रहे कि|रख दो|रख दें|कर ?दो|हो सके|हो सकता|ऑप्शन|दिखना|दिखाना|दिखाई|"
    r"\b(?:chahiye|rahega|rahenge|rakh do|ho sake|hona chahiye|dikhna|dikhana|option|i want|we want|want to see)\b", re.I)
HI_FEEDBACK = re.compile(
    r"नहीं दिख|दिख नहीं|दिख भी नहीं|दिख रहा|खुल नहीं|नहीं खुल|पहले जैसा|नहीं आ रहा|खाली|बोल रहा था|बात हुआ था|"
    r"\b(?:same old|old one|not visible|not showing|pehle jaisa|jaisa pehle|nahi dikh|nhi dikh|bol raha tha|want a copy)\b", re.I)
# delivery side asking the client to do something (check / share / send / go through)
ASK_CLIENT = re.compile(
    r"\b(?:send me|share me|share (?:kr|kar) ?do|send (?:kr|kar) ?do|mujhe (?:send|share|bhej)|go through|check (?:kr|kar) ?lo|(?:kr|kar)lo|"
    r"bta dena|bata dena|(?:please|pls|just) check|check the (?:app|website)|aap .{0,40}(?:send|share|check|bhej|bana)|"
    r"(?:send|share|check|bhej).{0,30}\baap\b)", re.I)
# "nahi" alone is a statement, not a pending task: a leftover-work cue is needed to propose an open TASK from a negation
PENDING_WORD = re.compile(r"\b(?:pending|baaki|baki|yet|abhi tak|not started|incomplete|remaining|left|to do|still)\b", re.I)
# "ok madam that will do" / "sure, I'll check": an acknowledgement, not a new commitment
ACK_COMMIT = re.compile(r"\b(?:that|it|this) (?:will|would) (?:do|be (?:fine|ok|okay|good)|work)\b", re.I)
DEVANAGARI = re.compile(r"[ऀ-ॿ]")
HINGLISH = re.compile(r"\b(?:hai|hain|nahi|nhi|kya|karo|kar|kr|ho|hua|mein|me|aap|apna|bhi|thik|theek|abhi|kal|aaj|kaise|kaisa|isme|iska|baat|agar|koi|fir|toh|to|mtlb|bhej|dekh|kijiye|krna|karna|rha|raha)\b", re.I)


def detect_language(text: str) -> str:
    if DEVANAGARI.search(text):
        return "hi"
    return "hinglish" if len(HINGLISH.findall(text)) >= 2 else "en"


def propose_category(m: Msg, sender_role: str, recent_bug: bool, has_deadline: bool, linked_task_created: bool) -> dict:
    s = signals(m.text)
    text = m.text.strip()
    words = len(text.split())
    client = sender_role in CLIENT_SIDE
    c: dict[str, float] = {}

    def add(cat, score):
        c[cat] = max(c.get(cat, 0.0), score)

    if CHATTER.match(text) or (words <= 2 and not any(s[k] for k in ("done", "assign", "question", "approval", "bug"))):
        add("GENERAL", 0.85)
    if s["blocked"]:
        add("TASK_BLOCKED", 0.8)
    if s["client_wait"]:
        add("CLIENT_PENDING", 0.85)
    if s["done"] and not s["neg_done"]:
        if s["bug_fixed"] and (recent_bug or s["bug"]):
            add("BUG_FIXED", 0.8)
        elif s["deploy"]:
            add("DEPLOYMENT", 0.8)
        else:
            add("TASK_COMPLETED", 0.7 + (0.1 if linked_task_created is not None else 0))
    elif s["bug_fixed"] and recent_bug:
        add("BUG_FIXED", 0.7)
    if s["deploy"] and not s["done"]:
        add("DEPLOYMENT", 0.6)
    if s["test_pass"]:
        add("TESTING", 0.8)
    if s["approval"]:
        add("CLIENT_APPROVAL", 0.75 if client else 0.55)
    if s["reject"] or (client and (COMPLAINT.search(text) or REVIEW_REQUEST.search(text))):
        add("CLIENT_FEEDBACK", 0.7 if client else 0.55)
    if s["bug"] and not s["question"]:
        add("BUG", 0.7)
    if s["reopen"]:
        add("BUG", 0.7)
    if s["req_change"]:
        add("REQUIREMENT_CHANGE", 0.8)
    if s["requirement"]:
        add("REQUIREMENT", 0.65 if client else 0.55)
    if s["decision"]:
        add("DECISION", 0.7)
    if s["meeting"]:
        add("MEETING", 0.72 if s["assign"] or s["question"] else 0.65)      # "can you / can we have a call" is a meeting ask, not a task
    if s["payment"] or PAY_REQUEST.search(text) or PAID.search(text):
        add("PAYMENT", 0.85 if PAY_REQUEST.search(text) else 0.65)
    if s["risk"]:
        add("RISK", 0.6)
    if s["assign"] and not s["done"]:
        # a client phrasing what the site should do ("setting kar do ki ...") states a requirement; the same words from the team assign work
        add("TASK", 0.7 + (0.1 if linked_task_created else 0))
        if client and (s["requirement"] or HI_REQUIREMENT.search(text)):
            add("REQUIREMENT", 0.85)
    if s["progress"]:
        add("TASK_IN_PROGRESS", 0.7)
    if s["neg_done"] and not s["done"] and PENDING_WORD.search(text):
        add("TASK", 0.55)
    if s["commit"] and not s["done"] and not ACK_COMMIT.search(text):
        add("DEADLINE" if has_deadline else "TASK", 0.5)
    if has_deadline and not (s["assign"] or s["commit"]):
        add("DEADLINE", 0.55)
    if sender_role == "SALES" and not c:
        add("SALES", 0.6)
    if s["question"]:
        add("QUESTION", 0.6)
    if HI_REQUIREMENT.search(text):
        add("REQUIREMENT", 0.62 if client else 0.5)
    if HI_FEEDBACK.search(text) and client:
        add("CLIENT_FEEDBACK", 0.65)
    if not client and sender_role != "OTHER" and ASK_CLIENT.search(text) and not s["done"]:
        add("CLIENT_PENDING", 0.72)
    if not c:
        add("DISCUSSION" if words >= 8 else "GENERAL", 0.4 if words >= 8 else 0.5)
    ranked = sorted(c.items(), key=lambda kv: -kv[1])
    cat, score = ranked[0]
    conf = score
    if len(ranked) > 1 and ranked[1][1] >= score - 0.1 and ranked[1][0] != "GENERAL":
        conf -= 0.15                      # two plausible readings -> be less sure
    if words < 4 and cat not in ("GENERAL",):
        conf -= 0.1                       # very short messages need context
    return {"category": cat, "confidence": round(max(0.2, min(conf, 0.95)), 2),
            "alternatives": [{"category": k, "confidence": round(v, 2)} for k, v in ranked[1:3]]}


def build_batch(chat_text: str, project: str, role_overrides: Optional[dict] = None, double: float = 0.10, seed: int = 1,
                context: int = 3, audit_share: float = 0.10, classifier=None) -> dict:
    parsed = WhatsAppParser().parse_text(chat_text)
    msgs = [Msg.from_parsed(m) for m in parsed]
    result = analyze(msgs, role_overrides=role_overrides, classifier=classifier)
    roles = {n: r["role"] for n, r in result["roles"].items()}

    task_no: dict[str, str] = {}
    created_by_msg: dict[str, dict] = {}
    for t in result["tasks"]:
        task_no[t["id"]] = f"T{len(task_no) + 1}"
        created_by_msg[t["source_message_id"]] = t
    trace: dict[tuple[str, str], str] = {}                 # (task id, message id) -> status after that message
    for t in result["tasks"]:
        for tr in t["status_trace"]:
            trace[(t["id"], tr["message_id"])] = tr["status"]
    flagged_cp = {mid for it in result["client_pending"] for mid in it["source_message_ids"][:1]}
    flagged_risk = {mid for r in result["risk"]["risks"] for mid in r["source_message_ids"][:1]}
    running: dict[str, str] = {}

    items = []
    recent_bug_idx = -99
    for i, (pm, m) in enumerate(zip(parsed, msgs)):
        if pm.is_system or pm.is_media or pm.is_deleted or not m.text.strip():
            continue
        sg = signals(m.text)
        if sg["bug"]:
            recent_bug_idx = i
        link = result["message_links"].get(m.id)
        created = created_by_msg.get(m.id)
        dl = extract_deadline(m.text, m.ts)
        prop = propose_category(m, roles.get(m.sender or "", "OTHER"), i - recent_bug_idx <= 12, dl is not None,
                                True if created else (None if not link else False))
        task = None
        status = None
        if link:
            task = link["task_id"]
            status = trace.get((task, m.id)) or running.get(task)
            if status:
                running[task] = status
        proposal = {**prop, "language": detect_language(m.text),
                    "status": status if prop["category"] in ("TASK", "TASK_COMPLETED", "TASK_IN_PROGRESS", "TASK_BLOCKED", "BUG_FIXED") else None,
                    "assignee": created["assigned_to"] if created else None,
                    "deadline_text": (created["deadline_text"] if created else None) or (dl.text if dl else None),
                    "task_key": task_no.get(task) if task else None,
                    "client_pending": m.id in flagged_cp, "risk": m.id in flagged_risk,
                    "sender_role": roles.get(m.sender or "", "OTHER"), "source": "rules" + ("+classifier" if classifier else ""),
                    "model_version": ENGINE_VERSION}
        before = [{"sender": x.sender_name, "text": x.text[:240]} for x in parsed[max(0, i - context):i] if not x.is_system]
        after = [{"sender": x.sender_name, "text": x.text[:240]} for x in parsed[i + 1:i + 1 + context] if not x.is_system]
        items.append({"message_id": m.id, "index": i, "timestamp": m.ts.isoformat(), "sender": m.sender, "message": m.text,
                      "context_before": before, "context_after": after, "proposal": proposal,
                      "lane": triage(prop["confidence"]), "double": False, "audit": False})

    rng = random.Random(seed)
    for it in rng.sample(items, k=round(len(items) * double)) if items else []:
        it["double"] = True                                  # a second annotator labels these independently (agreement / kappa)
    auto = [it for it in items if it["lane"] == "auto_accept"]
    for it in rng.sample(auto, k=min(len(auto), max(1, round(len(auto) * audit_share)))) if auto else []:
        it["audit"] = True                                   # auto-accepted proposals are spot-checked, not trusted blindly
    queue = [it for it in items if it["lane"] != "auto_accept" or it["audit"]]
    rare = {"BLOCKER", "BUG_FIXED", "REQUIREMENT_CHANGE", "CLIENT_APPROVAL", "RISK", "DECISION", "TASK_BLOCKED", "CLIENT_PENDING"}
    queue.sort(key=lambda it: (it["proposal"]["confidence"] - (0.1 if it["proposal"]["category"] in rare else 0), it["index"]))
    for rank, it in enumerate(queue):
        it["queue_rank"] = rank
    cats = Counter(it["proposal"]["category"] for it in items)
    return {"meta": {"project_id": project, "created_at": datetime.now(timezone.utc).isoformat(), "engine_version": ENGINE_VERSION,
                     "messages_total": len(parsed), "labelable": len(items), "in_queue": len(queue), "double_annotation": sum(it["double"] for it in items),
                     "lanes": dict(Counter(it["lane"] for it in items)), "proposed_categories": dict(cats.most_common()),
                     "roles_used": roles, "note": "Proposals are rule-based suggestions, not ground truth. Review every item."},
            "items": queue}


def annotation_stats(records: list[dict]) -> dict:
    """How good were the proposals? From saved annotations that carry model_prediction (the proposal shown to the annotator)."""
    seen = [r for r in records if r.get("model_prediction")]
    if not seen:
        return {"reviewed": 0}
    acc = [r["category"] == r["model_prediction"]["category"] for r in seen]
    per = {}
    for r, ok in zip(seen, acc):
        d = per.setdefault(r["model_prediction"]["category"], {"shown": 0, "accepted": 0})
        d["shown"] += 1
        d["accepted"] += int(ok)
    bands = {"<0.50": (0, .5), "0.50-0.70": (.5, .7), "0.70-0.85": (.7, .85), ">=0.85": (.85, 1.01)}
    calib = {}
    for name, (lo, hi) in bands.items():
        sel = [ok for r, ok in zip(seen, acc) if lo <= r["model_prediction"]["confidence"] < hi]
        calib[name] = {"n": len(sel), "accepted": round(sum(sel) / len(sel), 3) if sel else None}
    return {"reviewed": len(seen), "accept_rate": round(sum(acc) / len(acc), 3),
            "per_proposed_category": {k: {**v, "rate": round(v["accepted"] / v["shown"], 3)} for k, v in sorted(per.items())},
            "accept_rate_by_confidence": calib}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("chat"); ap.add_argument("out"); ap.add_argument("--project", default="project")
    ap.add_argument("--role", action="append", default=[], metavar="SENDER=ROLE")
    ap.add_argument("--double", type=float, default=0.10); ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args(argv)
    roles = dict(r.split("=", 1) for r in a.role)
    batch = build_batch(Path(a.chat).read_text(encoding="utf-8-sig"), a.project, roles, a.double, a.seed)
    Path(a.out).write_text(json.dumps(batch, ensure_ascii=False, indent=1), encoding="utf-8")
    m = batch["meta"]
    print(f"{m['labelable']} labelable messages -> {m['in_queue']} in queue, {m['double_annotation']} for double annotation; lanes {m['lanes']}")


if __name__ == "__main__":
    main()
