"""Task extraction, cross-message task resolution and evidence-based status.

Pass over messages in time order. A message either CREATES a task (assignment
intent + target + topic) or is EVIDENCE linked to the best matching task.
Completion needs strong evidence; ambiguous "done" never auto-completes.
"""
from __future__ import annotations

import hashlib
import math
import re
from datetime import timedelta
from typing import Optional

from app.intelligence.roles import CLIENT_SIDE
from app.intelligence.rules import norm, signals
from app.intelligence.temporal import extract_deadline
from app.intelligence.topics import (ALIASES, _TOKEN2GROUP, tokens as _tokens, find_people, make_title, sentence_from, topic_overlap,
                                     topic_set, vocative_target)
from app.intelligence.types import Evidence, Msg, Task

LINK_THRESHOLD = 0.42
MAX_CANDIDATES = 200  # bounds per-message work on huge projects; irrelevant below ~200 tasks sharing a word
CANCEL = re.compile(r"(?<!\w)(?:cancel(?:l)?ed|dropped|scrapped|no longer needed|not needed|remove(?:d)? from scope|drop the)(?!\w)", re.I)
URGENT = re.compile(r"\b(?:urgent|asap|critical|immediately|high priority|important|jaldi)\b", re.I)
LOW_PRI = re.compile(r"\b(?:low priority|whenever|when free|no rush|nice to have)\b", re.I)
EXT_DEP = re.compile(r"(credentials?|api keys?|access|approval|assets?|content|logo|server|api|design|confirmation|payment)", re.I)

SELF_ANNOUNCE = re.compile(r"\b(?:i'?ll|i will|i am going to|i'?m going to) (?:build|create|implement|develop|work on|set up|write|design|add|fix|prepare|take care of)\b(.+)", re.I)
NEED_OWNER = re.compile(r"\b(?:need(?:s)? (?:an |a )?(?:owner|someone|volunteer)|who can|can someone|anyone (?:can|free|to)|koi (?:le|kar) )", re.I)
TAKE_IT = re.compile(r"\b(?:i can take|i'?ll take|i will take|i can handle|i'?ll handle|i'?ll do (?:it|this)|i can do (?:it|this)|i got (?:it|this)|main (?:kar|le) (?:leta|lunga)|mai (?:kar|le) (?:leta|lunga)|main karta hu|mai karta hu)\b", re.I)
UNKNOWN_VOCATIVE = re.compile(r"^\s*(?:@([A-Z][a-z]{2,})|([A-Z][a-z]{2,})\s*[,:]\s)")
_NOT_NAMES = {"hi", "hello", "dear", "team", "guys", "everyone", "please", "thanks", "okay", "sir", "bhai"}
WEIGHT_BY_GROUP = {"payment": 5, "deploy": 5, "admin": 5, "api": 3, "db": 3, "notify": 3, "cart": 3,
                   "auth": 2, "design": 2, "search": 2, "invoice": 2, "doc": 1}
DOMAIN_BY_GROUP = {"design": "DESIGN", "deploy": "DEPLOYMENT", "doc": "DOCUMENTATION"}


def task_weight(topic: frozenset, text: str) -> float:
    if re.search(r"\b(?:architecture|migration of|rewrite|major)\b", text, re.I):
        return 8.0
    ws = [WEIGHT_BY_GROUP[g[1:]] for g in topic if g.startswith("@") and g[1:] in WEIGHT_BY_GROUP]
    return float(max(ws)) if ws else 2.0


def task_domain(topic: frozenset, text: str) -> str:
    for g in topic:
        if g.startswith("@") and g[1:] in DOMAIN_BY_GROUP:
            return DOMAIN_BY_GROUP[g[1:]]
    if re.search(r"\b(?:test|qa|regression|uat)\b", text, re.I):
        return "TESTING"
    return "DEVELOPMENT"


def task_priority(text: str, deadline, created) -> str:
    if re.search(r"\bcritical\b|production down", text, re.I):
        return "CRITICAL"
    if URGENT.search(text) or (deadline and deadline.when and deadline.when - created <= timedelta(days=2)):
        return "HIGH"
    if LOW_PRI.search(text):
        return "LOW"
    return "MEDIUM"


def _tid(source_message_id: str) -> str:
    return "task_" + hashlib.sha1(source_message_id.encode()).hexdigest()[:10]


def _first_name_key(n: str) -> str:
    return norm(re.sub(r"\(.*?\)|^(?:sales|pm|qa|dev)\s*-\s*|^(?:mr|mrs|ms|dr)\.?\s+", "", n, flags=re.I)).split(" ")[0] if n else ""


def build_tasks(msgs: list[Msg], roles: dict[str, dict], as_of=None, linker=None):
    """Return (tasks, links). links: message_id -> {task_id, score, kind}."""
    names = list(roles.keys())
    if linker is not None:
        linker.prepare(msgs)
    tasks: list[Task] = []
    by_token: dict[str, list[Task]] = {}      # topic token -> tasks (candidates must share a token to overlap)
    by_assignee: dict[str, list[Task]] = {}
    links: dict[str, dict] = {}
    last_touched: dict[str, Task] = {}  # sender -> last task they touched/were assigned

    def role(n):
        return roles.get(n, {}).get("role", "OTHER")

    for pos, m in enumerate(msgs):
        if not m.sender:
            continue
        s = signals(m.text)
        low = norm(m.text)

        # ---- 0. volunteering ("need an owner" ... "I can take it") -----------------
        if TAKE_IT.search(m.text) and not s["question"] and role(m.sender) not in CLIENT_SIDE:
            prev = next((p for p in reversed(msgs[max(0, pos - 4):pos]) if p.sender and p.sender != m.sender
                         and NEED_OWNER.search(p.text) and 0 <= (m.ts - p.ts).total_seconds() <= 1800), None)
            if prev is not None:
                title = make_title(re.sub(NEED_OWNER, "", prev.text), [])
                topic = topic_set(title or prev.text)
                if topic and title and not any(t.source_message_id == prev.id for t in tasks):
                    dl = extract_deadline(m.text, m.ts) or extract_deadline(prev.text, prev.ts)
                    t = Task(id=_tid(prev.id), title=title, topic=topic, assignee=m.sender, created_by=prev.sender,
                             source_message_id=prev.id, created_at=prev.ts, deadline=dl, confidence=0.7, last_touch=m.ts)
                    t.status_trace.append({"message_id": prev.id, "event": "created", "status": "TODO"})
                    t.evidence.append(Evidence(m.id, "volunteered"))
                    tasks.append(t)
                    by_assignee.setdefault(m.sender, []).append(t)
                    for tok in t.topic:
                        by_token.setdefault(tok, []).append(t)
                    links[m.id] = {"task_id": t.id, "score": 0.8, "kind": "volunteered"}
                    last_touched[m.sender] = t
                    continue

        # ---- 0b. self-announced work ("I'll build the booking screen") by a team member ---------
        sa = SELF_ANNOUNCE.search(m.text) if role(m.sender) not in CLIENT_SIDE and not s["question"] else None
        if sa and not s["done"]:
            title = make_title(m.text[sa.start():], [])
            topic = topic_set(title or sa.group(1))
            if topic and title and not any(t.assignee == m.sender and topic_overlap(t.topic, topic) >= 0.8 and m.ts - t.created_at < timedelta(days=14) for t in by_assignee.get(m.sender, ())):
                dl = extract_deadline(m.text, m.ts)
                t = Task(id=_tid(m.id), title=title, topic=topic, assignee=m.sender, created_by=m.sender, source_message_id=m.id,
                         created_at=m.ts, deadline=dl, confidence=0.6, last_touch=m.ts, needs_review=True, review_reasons=["self-announced task (nobody assigned it)"])
                t.status_trace.append({"message_id": m.id, "event": "created", "status": "TODO"})
                tasks.append(t)
                by_assignee.setdefault(m.sender, []).append(t)
                for tok in t.topic:
                    by_token.setdefault(tok, []).append(t)
                links[m.id] = {"task_id": t.id, "score": 0.7, "kind": "self_announced"}
                last_touched[m.sender] = t
                continue

        # ---- 1. task creation -------------------------------------------------
        assignish = (s["assign"] or (m.category == "TASK" and m.cat_conf >= 0.6)) and not s["done"] and not s["neg_done"]
        target = vocative_target(m.text, [n for n in names if n != m.sender])
        mentioned = [p for p in find_people(m.text, [n for n in names if n != m.sender])]
        at_mention = bool(re.match(r"\s*@[A-Z]", m.text))
        if assignish and (target or at_mention or not s["question"]):
            assignee = target or (mentioned[0] if mentioned else None)
            via = 0.2 if target else (0.12 if assignee else 0.0)
            unknown_name = False
            if not assignee:  # "Sneha, mockup banana hai ..." where Sneha has not spoken yet
                um = UNKNOWN_VOCATIVE.match(m.text)
                nm = um and (um.group(1) or um.group(2))
                if nm and nm.lower() not in _NOT_NAMES:
                    assignee, via, unknown_name = nm, 0.1, True
            if assignee and role(assignee) in CLIENT_SIDE:
                continue  # "Anil, please share the token" -> handled by the client-pending engine, not a team task
            if role(m.sender) in CLIENT_SIDE and not assignee:
                assignee = None
                continue  # a client message without a named team member is a requirement, not a task
            focus = sentence_from(m.text, target) if target else m.text   # only the sentence addressed to the assignee
            title = make_title(focus, [assignee] if assignee else [])
            topic = topic_set(title or focus)
            if title and len(topic) <= 2 and not any(x.startswith("@") for x in topic):
                # bare "integrate" / "banao": the object was named just before ("Razorpay final. Yash tum integrate karo")
                before = m.text[:max(0, m.text.find(focus))] if focus != m.text else ""
                prev = msgs[pos - 1] if pos else None
                ctx = before + " " + (prev.text if prev is not None and prev.sender and (m.ts - prev.ts).total_seconds() <= 900 else "")
                words = [w for w in _tokens(ctx) if w in _TOKEN2GROUP][:2]
                if words:
                    title = (" ".join(w.title() for w in dict.fromkeys(words)) + " " + title).strip()
                    topic = topic_set(title)
            if topic and title and (assignee or role(m.sender) in {"PROJECT_MANAGER", "CLIENT", "CLIENT_REPRESENTATIVE", "SALES", "ADMIN"}):
                dl = extract_deadline(m.text, m.ts)
                dup = next((t for t in reversed(by_assignee.get(assignee, [])) if t.status != "COMPLETED"
                            and topic_overlap(t.topic, topic) >= 0.8 and m.ts - t.created_at < timedelta(days=14)), None)
                if dup:  # reminder / re-assignment of same work -> evidence, not a new task
                    dup.evidence.append(Evidence(m.id, "reminder"))
                    if dl and not dup.deadline:
                        dup.deadline = dl
                    links[m.id] = {"task_id": dup.id, "score": 0.9, "kind": "duplicate_assignment"}
                    continue
                conf = 0.5 + via + (0.1 if dl else 0) + (0.1 if m.category == "TASK" else 0) + \
                    (0.1 if role(m.sender) in {"PROJECT_MANAGER", "CLIENT", "CLIENT_REPRESENTATIVE", "SALES"} else 0)
                t = Task(id=_tid(m.id), title=title, topic=topic, assignee=assignee, created_by=m.sender,
                         source_message_id=m.id, created_at=m.ts, deadline=dl, confidence=round(min(conf, 0.95), 2),
                         last_touch=m.ts)
                t.status_trace.append({"message_id": m.id, "event": "created", "status": "TODO"})
                if unknown_name:
                    t.needs_review = True
                    t.review_reasons.append("assignee is not a known chat participant")
                if not assignee:
                    t.needs_review = True
                    t.review_reasons.append("no assignee identified")
                if t.confidence < 0.7:
                    t.needs_review = True
                    t.review_reasons.append(f"low extraction confidence {t.confidence}")
                tasks.append(t)
                by_assignee.setdefault(assignee, []).append(t)
                for tok in t.topic:
                    by_token.setdefault(tok, []).append(t)
                links[m.id] = {"task_id": t.id, "score": 1.0, "kind": "created"}
                if assignee:
                    last_touched[assignee] = t
                continue

        # ---- 2. evidence linking ---------------------------------------------
        evid = {k for k in ("done", "progress", "blocked", "client_wait", "test_pass", "deploy", "bug", "bug_fixed",
                            "reopen") if s[k]} | ({"cancel"} if CANCEL.search(low) else set())
        dl_only = extract_deadline(m.text, m.ts) if re.search(r"\bdeadline\b|\bdue\b|\bready by\b", low) else None
        if not evid and not dl_only:
            continue
        mt = topic_set(m.text)
        best, second, bscore = None, None, 0.0
        cands = []
        if linker is not None:      # embeddings can match tasks that share no token -> scan everything
            pool = tasks
        else:                       # lexical overlap needs a shared token: look tasks up in the inverted index
            seen: dict[int, Task] = {}
            for tok in mt:
                for t in by_token.get(tok, ()):
                    seen[id(t)] = t
            pool = list(seen.values())
            if len(pool) > MAX_CANDIDATES:   # very common words ("payment"): keep the most recently touched + the sender's own tasks
                pool = sorted(pool, key=lambda t: t.last_touch or t.created_at, reverse=True)[:MAX_CANDIDATES]
                mine = {id(t) for t in pool}
                pool += [t for t in by_assignee.get(m.sender, ())[-20:] if id(t) not in mine and id(t) in seen]
        for t in pool:
            ov = topic_overlap(mt, t.topic)
            if linker is not None:  # embeddings rescue paraphrases that share no words
                ov = max(ov, linker.sim(m.id, t.title))
            days = (m.ts - (t.last_touch or t.created_at)).total_seconds() / 86400
            sc = 0.55 * ov + 0.25 * (m.sender == t.assignee) + 0.12 * math.exp(-max(days, 0) / 7) + \
                0.08 * (last_touched.get(m.sender) is t)
            cands.append((sc, ov, t))
        cands.sort(key=lambda x: -x[0])
        kind = "topic"
        top_ov = cands[0][1] if cands else 0.0
        if cands and top_ov >= 0.25:
            sc, ov, t = cands[0]
            if sc >= LINK_THRESHOLD:
                best, bscore = t, sc
                if len(cands) > 1 and cands[1][1] >= 0.25 and sc - cands[1][0] < 0.05:
                    kind = "ambiguous"
        else:  # no topical candidate: a content-free message ("Done") by the assignee -> their last touched task
            lt = last_touched.get(m.sender)
            if lt is not None and len(mt) == 0 and (m.ts - (lt.last_touch or lt.created_at)) < timedelta(days=3):
                best, bscore, kind = lt, 0.45, "context"
        if best is None:
            continue
        links[m.id] = {"task_id": best.id, "score": round(bscore, 2), "kind": kind}
        _apply(best, m, s, evid, bscore, kind, dl_only, role)
        best.last_touch = m.ts
        last_touched[m.sender] = best

    for t in tasks:
        if t.status != "COMPLETED" and t.deadline and t.deadline.when and as_of and t.deadline.when < as_of:
            t.needs_review = t.needs_review  # overdue computed by risk engine; keep status untouched
    return tasks, links


def _apply(t: Task, m: Msg, s: dict, evid: set, score: float, kind: str, dl_only, role):
    def set_status(new, why):
        if new != t.status:
            t.status_trace.append({"message_id": m.id, "event": why, "from": t.status, "status": new})
            t.status = new

    for sig in sorted(evid):
        t.evidence.append(Evidence(m.id, sig, round(score, 2)))
    if dl_only and not t.deadline:
        t.deadline = dl_only
    if "cancel" in evid and kind != "context":
        set_status("CANCELLED", "cancelled")
        return
    topical = kind in ("topic",) and score >= 0.55
    from_assignee = m.sender == t.assignee

    if "reopen" in evid:
        t.completed_at = None
        set_status("IN_PROGRESS", "reopened")
        t.needs_review = True
        t.review_reasons.append("reopened after completion claim")
        return
    if "blocked" in evid or "client_wait" in evid:
        dep = None
        if "client_wait" in evid:
            from app.intelligence.rules import client_pending_type
            dep = f"CLIENT:{client_pending_type(m.text)}"
        else:
            mm = EXT_DEP.search(m.text)
            dep = mm.group(1).lower() if mm else None
        if t.status != "COMPLETED":
            set_status("BLOCKED", "blocked_by_dependency" if (s["done"] or s["weak_done"]) else "blocked")
            t.external_dependency = dep or t.external_dependency
            return
    strong_done = s["done"] and (topical or (from_assignee and kind == "topic"))
    if s["done"] and not strong_done:  # context-only / ambiguous link
        if t.status == "TODO":
            set_status("IN_PROGRESS", "ambiguous_done")
        t.needs_review = True
        t.review_reasons.append("completion claimed but task link is ambiguous")
        t.evidence[-1].weight = min(t.evidence[-1].weight, 0.45)
        t.confidence = round(min(t.confidence, 0.6), 2)
        return
    if strong_done and not s["bug"] or (strong_done and s["bug_fixed"]):
        if t.status != "CANCELLED":
            set_status("COMPLETED", "completed")
            t.completed_at = t.completed_at or m.ts
            t.external_dependency = None
            t.confidence = round(min(0.95, t.confidence + 0.1 + (0.05 if from_assignee else 0)), 2)
        return
    if (s["test_pass"] or s["deploy"]) and not s["progress"]:
        was_ambiguous = any(r.startswith("completion claimed") for r in t.review_reasons)
        if t.status in ("IN_PROGRESS", "TODO") and (was_ambiguous or s["deploy"] and ("@deploy" in t.topic)):
            set_status("COMPLETED", "completed_via_test_or_deploy")
            t.completed_at = t.completed_at or m.ts
            t.needs_review = False if was_ambiguous and t.review_reasons == ["completion claimed but task link is ambiguous"] else t.needs_review
        elif t.status == "COMPLETED":
            t.confidence = round(min(0.97, t.confidence + 0.03), 2)
        return
    if "progress" in evid and t.status in ("TODO", "BLOCKED") and not ("blocked" in evid):
        set_status("IN_PROGRESS", "progress")
    if "bug" in evid and t.status == "COMPLETED" and m.sender != t.assignee:
        t.needs_review = True
        t.review_reasons.append("bug reported after completion")
