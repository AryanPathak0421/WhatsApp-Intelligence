"""Sentiment, frustration and urgency: a transparent LEXICON baseline for English / Hinglish / Devanagari Hindi, with negation handling.

This is model-free inference, not ground truth. Every result lists the words that triggered it (so a reviewer can disagree), neutral is the default
(no cue -> NEUTRAL), and sarcasm / irony / long-range context are NOT handled. Its accuracy has only been checked on author-written examples
(tests/test_sentiment.py), never on independently labelled real chats, so treat scores as signals for review, not measurements.
Aggregates (counts, per-sender and per-day) are arithmetic over these per-message labels.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Optional

from app.intelligence.rules import norm
from app.intelligence.types import Msg

POS = {
    "thanks", "thank", "thankyou", "great", "good", "nice", "awesome", "perfect", "excellent", "love", "happy", "amazing", "wonderful", "superb", "fantastic",
    "appreciate", "appreciated", "brilliant", "well", "smooth", "impressive", "glad", "pleased", "satisfied",
    "shukriya", "dhanyavad", "dhanyawad", "badhiya", "badiya", "mast", "zabardast", "shandar", "khush", "achha", "accha", "acha", "sahi", "bahut",
    "बढ़िया", "धन्यवाद", "शुक्रिया", "अच्छा", "बहुत", "शानदार", "खुश", "बेहतरीन",
}
POS_STRONG = {"awesome", "perfect", "excellent", "amazing", "wonderful", "superb", "fantastic", "brilliant", "zabardast", "shandar", "बेहतरीन", "शानदार"}
POS_WEAK_ONLY_WITH_OTHER = {"bahut", "well", "sahi", "बहुत"}                       # too common to count alone
NEG = {
    "bad", "worst", "wrong", "issue", "issues", "problem", "problems", "bug", "bugs", "error", "errors", "fail", "failed", "failing", "failure", "broken",
    "crash", "crashed", "delay", "delayed", "disappointed", "disappointing", "unhappy", "angry", "annoyed", "annoying", "poor", "terrible", "horrible",
    "useless", "waste", "slow", "stuck", "mistake", "complaint", "complain", "confusing", "confused", "worried", "concern", "concerned", "unacceptable",
    "galat", "kharab", "dikkat", "pareshani", "pareshan", "problem", "gadbad", "nuksan", "bekar", "bakwas", "naraz",
    "गलत", "खराब", "दिक्कत", "समस्या", "परेशान", "परेशानी", "बकवास", "नाराज़", "नाराज", "देरी", "गड़बड़",
}
FRUSTRATION = re.compile(
    r"(?:\bagain\b|\bstill\b|\balready\b)[^.?!\n]{0,25}(?:not|nahi|nhi|issue|problem|same|wrong|error)|"
    r"\b(?:wrong|broken|failed|failing|error|crashed|not working|bug)\b[^.?!\n]{0,15}\bagain\b|\bhow many times\b|\bkitni (?:baar|bar)\b|"
    r"\bwhy (?:is|are|does|do|did) .{0,30}(?:still|again|not)\b|\bfed up\b|\bfrustrat\w+|\birritat\w+|\buseless\b|\bwaste of\b|\bridiculous\b|\bunacceptable\b|"
    r"\bpareshan\b|\bparesaan\b|\btang aa\b|\bbakwas\b|\babhi tak (?:nahi|nhi)\b|\bkab tak\b|\bsame (?:issue|problem|error)\b|\bagain and again\b|\bbaar baar\b|"
    r"फिर से|अभी तक नहीं|कब तक|कितनी बार|बकवास|परेशान|बार बार", re.I)
URGENT = re.compile(
    r"\burgent(?:ly)?\b|\basap\b|\bimmediate(?:ly)?\b|\bright now\b|\bemergency\b|\bcritical\b|\bhigh priority\b|\bby eod\b|\btoday itself\b|\bwithout delay\b|"
    r"\bjaldi\b|\bturant\b|\bturat\b|\baaj hi\b|\babhi ke abhi\b|\bfaaltu me time nahi\b|\bimportant\b|\bplease (?:reply|respond|confirm) (?:asap|today|now)\b|"
    r"जल्दी|तुरंत|अभी के अभी|आज ही|ज़रूरी|जरूरी", re.I)
NEGATORS = {"not", "no", "never", "n't", "dont", "don't", "isnt", "isn't", "wasnt", "wasn't", "cant", "can't", "without", "nahi", "nhi", "nahin", "na", "mat", "नहीं", "न"}
NO_PROBLEM = re.compile(r"\bno (?:issue|issues|problem|problems|worries|bug|bugs|error|errors)\b|\bnot a (?:problem|issue)\b|\bkoi (?:dikkat|problem|issue) nahi\b|"
                        r"\bno need to worry\b|कोई (?:दिक्कत|समस्या) नहीं", re.I)
EMOJI_POS = set("😊😀😁😃😄🙂😍🥰👍👌🙏❤💯🎉✅🤝😎")
EMOJI_NEG = set("😡😠😤😞😔😢😭👎😒🤦😩😫😖💔")
WORD = re.compile(r"[\w']+|[^\s\w]", re.UNICODE)


def _tokens(text: str) -> list[str]:
    return [t for t in WORD.findall(norm(text)) if t.strip()]


def score_message(text: str) -> dict:
    """{label, score in [-1,1], frustration, urgency in [0,1], evidence}. NEUTRAL when no cue is found."""
    t = norm(text or "")
    toks = _tokens(text or "")
    pos, neg, ev = 0.0, 0.0, []
    no_prob = bool(NO_PROBLEM.search(t))
    for i, w in enumerate(toks):
        if w in POS and w not in POS_WEAK_ONLY_WITH_OTHER:
            weight = 1.5 if w in POS_STRONG else 1.0
            window = toks[max(0, i - 3):i]
            if any(x in NEGATORS for x in window):                      # "not good" -> negative
                neg += weight
                ev.append(f"not {w}")
            else:
                pos += weight
                ev.append(w)
        elif w in NEG:
            window = toks[max(0, i - 3):i]
            if no_prob and w in {"issue", "issues", "problem", "problems", "bug", "bugs", "error", "errors", "dikkat", "worries", "समस्या", "दिक्कत"}:
                continue
            if any(x in NEGATORS for x in window) and w not in {"not"}:
                pos += 0.5                                              # "not bad", "no delay"
                ev.append(f"not {w}")
            else:
                neg += 1.0
                ev.append(w)
    if any(w in {"nahi", "nhi", "not", "नहीं"} for w in toks) and ("working" in toks or "chal" in toks or "chalra" in toks or "work" in toks or "kaam" in toks):
        neg += 1.0
        ev.append("not working")
    for ch in text or "":
        if ch in EMOJI_POS:
            pos += 0.7
            ev.append(ch)
        elif ch in EMOJI_NEG:
            neg += 1.0
            ev.append(ch)
    frustration = bool(FRUSTRATION.search(t)) or bool(re.search(r"[!?]{3,}", text or "")) or (
        len(re.findall(r"[A-Z]{4,}", text or "")) >= 2 and neg > 0)
    if frustration:
        neg += 1.0
        ev.append("frustration cue")
    urgency = 0.0
    if URGENT.search(t):
        urgency = 0.7
        ev.append("urgency cue")
        if re.search(r"!{2,}", text or "") or re.search(r"\b(?:urgent|asap|immediately|turant|jaldi)\b.*\b(?:urgent|asap|immediately|turant|jaldi)\b", t):
            urgency = 1.0
    raw = pos - neg
    denom = max(1.0, pos + neg)
    score = round(max(-1.0, min(1.0, raw / denom)), 2) if (pos or neg) else 0.0
    label = "POSITIVE" if score >= 0.25 else "NEGATIVE" if score <= -0.25 else "NEUTRAL"
    return {"label": label, "score": score, "frustration": frustration, "urgency": urgency, "evidence": ev[:8]}


def analyze_sentiment(msgs: list[Msg], roles: dict[str, dict], max_items: int = 200) -> dict:
    per, items = Counter(), []
    by_sender: dict[str, Counter] = defaultdict(Counter)
    by_day: dict[str, Counter] = defaultdict(Counter)
    frustrated_by: Counter = Counter()
    n = 0
    for m in msgs:
        if not m.text or m.text.strip().lower() in ("<media omitted>",):
            continue
        r = score_message(m.text)
        n += 1
        per[r["label"]] += 1
        who = m.sender or "(system)"
        by_sender[who][r["label"]] += 1
        by_day[m.ts.strftime("%Y-%m-%d")][r["label"]] += 1
        if r["frustration"]:
            frustrated_by[who] += 1
        if r["label"] != "NEUTRAL" or r["frustration"] or r["urgency"]:
            items.append({"message_id": m.id, "sender": m.sender, "sender_role": roles.get(m.sender or "", {}).get("role"), "ts": m.ts, **r})
    items.sort(key=lambda x: (-(x["urgency"] + (1 if x["frustration"] else 0) + abs(x["score"])), x["ts"]))
    role_of = {k: v.get("role") for k, v in roles.items()}
    client = Counter()
    for who, c in by_sender.items():
        if role_of.get(who) in ("CLIENT", "CLIENT_REPRESENTATIVE"):
            client.update(c)
    return {
        "counts": {"messages_scored": n, **{k: per.get(k, 0) for k in ("POSITIVE", "NEUTRAL", "NEGATIVE")},
                   "frustrated": sum(1 for x in items if x["frustration"]), "urgent": sum(1 for x in items if x["urgency"] > 0)},
        "by_sender": {k: dict(v) for k, v in by_sender.items()},
        "client_sentiment": dict(client),
        "frustration_by_sender": dict(frustrated_by),
        "by_day": {k: dict(v) for k, v in sorted(by_day.items())},
        "items": items[:max_items],
        "method": "lexicon baseline (EN/Hinglish/Hindi) with negation handling; model inference, not ground truth; sarcasm not handled",
    }
