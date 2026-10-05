"""Question / answer analytics: who asked, whether it was answered, by whom, how fast. Deterministic, evidence-bound.

A question is only marked ANSWERED when a later message from a DIFFERENT person is supported by evidence that it answers THIS question:
topical overlap with the question, being addressed (vocative / @mention) and replying, answer-shaped content for the question type
(a date for "kab", a yes/no for a polar question, a link for "link?"), and closeness in time. Bare acknowledgements ("ok", "hmm") never
answer a question that needs content. Weak evidence yields POSSIBLY_ANSWERED, which is NOT counted as answered and is flagged for review.
Counts, times and rates are plain arithmetic on those decisions; no model is involved.
"""
from __future__ import annotations

import re
import statistics
from datetime import datetime, timedelta
from typing import Optional

from app.intelligence.roles import CLIENT_SIDE
from app.intelligence.temporal import extract_deadline
from app.intelligence.topics import find_people, topic_overlap, topic_set, vocative_target
from app.intelligence.types import Msg

WINDOW = timedelta(hours=48)
MAX_LOOKAHEAD = 40
WH = re.compile(r"(?<!\w)(?:kya|kab|kaun|kaise|kyun|kyu|kyon|kitna|kitni|kitne|kidhar|kahan|kahaan|where|when|who|whom|how|why|what|which|"
                r"क्या|कब|कौन|कैसे|क्यों|कितना|कितनी|कहाँ|कहां)(?!\w)", re.I)
REQUEST_POLAR = re.compile(r"(?<!\w)(?:can|could|would|will|shall|should) (?:we|you|u|i)\b|\b(?:are|is|do|did|have|has) (?:you|we|this|it|that)\b|"
                           r"(?:right|okay|ok|or not|kar sakte|kar sakta|kar doge|ho sakta|ho jayega|hai na|na)\s?\?+\s*$", re.I)
AFFIRM = re.compile(r"^\W*(?:ok(?:ay|y|h)?|sure|fine|alright|thik(?: hai| h)?|theek(?: hai| h)?|done|cool|great|yes|yeah|yep|haan|han|ha|ji|ji haan|bilkul|ठीक है|हाँ|हां|जी|ओके)\b", re.I)
POLAR_START = re.compile(r"^\W*(?:is|are|was|were|do|does|did|can|could|will|would|should|have|has|kya|क्या|can we|are we)\b", re.I)
TAG_QUESTION = re.compile(r"^\W*(?:ok|okay|right|na|hai na|theek hai|thik hai|sahi|yes|no|haan|han|sure)\W*\?+\W*$", re.I)
ACK = re.compile(r"^\W*(?:ok(?:ay|y|h)?|hmm+|thanks?|thank you|thik(?: hai| h)?|theek(?: hai)?|sure|noted|got it|ji|acha|accha|achha|alright|fine|cool|great|"
                 r"ठीक है|जी|ओके|हम्म)\W*$", re.I)
YES_NO = re.compile(r"^\W*(?:yes|yeah|yep|no|nope|nahi|nhi|nahin|haan|han|ha|ji haan|bilkul|sure|correct|right|ho gaya|ho gya|done|हाँ|हां|नहीं|जी)\b", re.I)
LINK = re.compile(r"<url>|https?://|\bwww\.", re.I)
MEDIA = re.compile(r"^\s*<media omitted>\s*$", re.I)
NUMBERISH = re.compile(r"\b\d[\d,.:/-]*\b")
LINK_ASK = re.compile(r"\b(?:link|url|file|doc|document|screenshot|invoice|report)\b", re.I)
STATUS_ASK = re.compile(r"\b(?:update|status|progress|eta|done|ready|hua|hogaya|ho gaya|complete|kaha tak|kahan tak|where are we)\b", re.I)


def question_type(text: str) -> str:
    t = text.lower()
    if re.search(r"(?<!\w)(?:kab|when|कब)(?!\w)", t) or re.search(r"(?<!\w)(?:what time|which day|how long|kitne baje|kis time|kis din)(?!\w)", t) or re.search(r"\b(?:deadline|eta|by when)\b", t):
        return "when"
    if re.search(r"(?<!\w)(?:kaun|who|whom|कौन)(?!\w)", t):
        return "who"
    if STATUS_ASK.search(t):
        return "status"
    if LINK_ASK.search(t):
        return "artifact"
    if POLAR_START.search(t) or (REQUEST_POLAR.search(t) and not WH.search(t)):
        return "polar"
    return "wh"


def is_question(text: str) -> tuple[bool, float]:
    """(is it a question, confidence). Conservative: tag questions ("ok?", "hai na?") and one-word queries do not count."""
    t = (text or "").strip()
    if not t or MEDIA.match(t):
        return False, 0.0
    body = re.sub(r"<[^>]+>|@\w+", " ", t).strip()                 # <url>, <media omitted>, @mentions do not make a question
    words = re.findall(r"\w+", body)
    if len(words) < 2 or TAG_QUESTION.match(body):
        return False, 0.0
    has_q = bool(re.search(r"[?？]", body))
    wh = bool(WH.search(body))
    if has_q and (wh or len(words) >= 3):
        return True, 0.92 if wh else 0.85
    if has_q:
        return True, 0.6
    if wh and len(words) >= 3 and POLAR_START.search(body):
        return True, 0.6
    return False, 0.0


def _answer_shaped(qtype: str, text: str, ts: datetime) -> float:
    if qtype == "when":
        return 0.3 if (extract_deadline(text, ts) or re.search(r"\b(?:today|tomorrow|tonight|kal|aaj|abhi|monday|tuesday|wednesday|thursday|friday|saturday|sunday|\d{1,2}\s?(?:am|pm)|\d{1,2}:\d{2})\b", text, re.I)) else 0.0
    if qtype == "polar":
        return 0.35 if (YES_NO.search(text) or AFFIRM.search(text)) else 0.0
    if qtype == "artifact":
        return 0.3 if (LINK.search(text) or re.search(r"<media omitted>", text, re.I)) else 0.0
    if qtype == "who":
        return 0.2 if re.search(r"\b(?:me|main|mai|i|i'll|i will|ji)\b|@\w+", text, re.I) else 0.0
    if qtype == "status":
        return 0.25 if (YES_NO.search(text) or re.search(r"\b(?:done|ready|working|progress|pending|completed|ho gaya|hogaya|kal|tomorrow|soon)\b", text, re.I) or NUMBERISH.search(text)) else 0.0
    return 0.05 if NUMBERISH.search(text) or LINK.search(text) else 0.0


def _score(q: Msg, c: Msg, qtype: str, q_topics: frozenset, names: list[str], rank: int) -> tuple[float, list[str]]:
    why: list[str] = []
    text = c.text or ""
    if MEDIA.match(text):
        return 0.0, []
    if ACK.match(text) and qtype != "polar":
        return 0.0, []                                              # "ok" does not answer "when/what/who/how"
    s = 0.0
    target = vocative_target(q.text, names) if names else None
    if target and c.sender == target:
        s += 0.35
        why.append("addressed person replied")
    ov = topic_overlap(q_topics, topic_set(text)) if q_topics else 0.0
    if ov > 0:
        s += 0.4 * ov
        why.append(f"topic overlap {ov:.2f}")
    shape = _answer_shaped(qtype, text, c.ts)
    if shape:
        s += shape
        why.append(f"answer-shaped for a '{qtype}' question")
    gap = c.ts - q.ts
    near = 0.15 if gap <= timedelta(minutes=10) else 0.1 if gap <= timedelta(hours=1) else 0.05 if gap <= timedelta(hours=6) else 0.0
    if near:
        s += near * (1.0 if rank == 0 else 0.5)                    # closeness counts most for the first real (non-ack) reply
        why.append(f"reply {int(gap.total_seconds() // 60)} min later")
    if is_question(text)[0] and shape == 0:
        s *= 0.5                                                    # a counter-question is rarely the answer
    return min(1.0, s), why


def detect_qa(msgs: list[Msg], roles: dict[str, dict], as_of: Optional[datetime] = None) -> dict:
    as_of = as_of or (msgs[-1].ts if msgs else datetime.utcnow())
    names = [n for n in roles if n]
    items = []
    for i, q in enumerate(msgs):
        ok, qconf = is_question(q.text)
        if not ok or not q.sender:
            continue
        qtype = question_type(q.text)
        q_topics = topic_set(q.text)
        best, best_why, best_msg, rank = 0.0, [], None, 0
        for c in msgs[i + 1:i + 1 + MAX_LOOKAHEAD]:
            if c.ts - q.ts > WINDOW:
                break
            if not c.sender or c.sender == q.sender or c.text is None:
                continue
            sc, why = _score(q, c, qtype, q_topics, names, rank)
            if not (ACK.match(c.text) or MEDIA.match(c.text)):
                rank += 1
            if sc > best:
                best, best_why, best_msg = sc, why, c
        if best >= 0.5:
            status = "ANSWERED"
        elif best >= 0.3:
            status = "POSSIBLY_ANSWERED"
        else:
            status = "UNANSWERED"
        mins = round((best_msg.ts - q.ts).total_seconds() / 60, 1) if status == "ANSWERED" else None
        items.append({
            "id": f"qa_{q.id}", "question_message_id": q.id, "asked_by": q.sender, "asker_role": roles.get(q.sender, {}).get("role"),
            "asked_at": q.ts, "text": q.text.strip()[:240], "type": qtype, "status": status,
            "answer_message_id": best_msg.id if best_msg and status != "UNANSWERED" else None,
            "answered_by": best_msg.sender if best_msg and status != "UNANSWERED" else None,
            "answerer_role": roles.get(best_msg.sender, {}).get("role") if best_msg and status != "UNANSWERED" else None,
            "response_minutes": mins, "confidence": round(min(qconf, 0.99) * (0.6 + 0.4 * best) if status != "UNANSWERED" else qconf, 2),
            "needs_review": status == "POSSIBLY_ANSWERED" or qconf < 0.7, "reasons": best_why,
            "age_hours": round((as_of - q.ts).total_seconds() / 3600, 1) if status == "UNANSWERED" else None,
            "evidence_message_ids": [q.id] + ([best_msg.id] if best_msg and status != "UNANSWERED" else []),
        })
    answered = [x for x in items if x["status"] == "ANSWERED"]
    times = [x["response_minutes"] for x in answered if x["response_minutes"] is not None]
    unanswered = [x for x in items if x["status"] == "UNANSWERED"]
    by_role: dict[str, dict] = {}
    for x in items:
        r = by_role.setdefault(x["asker_role"] or "UNKNOWN", {"asked": 0, "answered": 0})
        r["asked"] += 1
        r["answered"] += x["status"] == "ANSWERED"
    client_unanswered = [x for x in unanswered if (x["asker_role"] in CLIENT_SIDE)]
    return {
        "items": items,
        "stats": {
            "total_questions": len(items), "answered": len(answered), "possibly_answered": sum(x["status"] == "POSSIBLY_ANSWERED" for x in items),
            "unanswered": len(unanswered), "answer_rate": round(len(answered) / len(items), 3) if items else None,
            "median_response_minutes": round(statistics.median(times), 1) if times else None,
            "mean_response_minutes": round(statistics.fmean(times), 1) if times else None,
            "client_questions_unanswered": len(client_unanswered), "by_asker_role": by_role,
            "oldest_unanswered_hours": max((x["age_hours"] for x in unanswered), default=None),
        },
        "method": "rules: question detection + evidence-scored answer matching (no model); POSSIBLY_ANSWERED is not counted as answered",
    }
