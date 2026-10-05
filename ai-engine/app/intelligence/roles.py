"""Role inference: admin override > name pattern > behaviour. Never message count alone.

Behaviour has two layers:
  1. WHICH SIDE of the relationship a person is on (client side vs delivery/vendor side) from how they talk:
     clients review, complain, ask "how far is the work", approve / hold the project, pay;
     delivery people post update lists, ask for payments / credentials / meetings, report finished work.
  2. WHAT they do on the delivery side (QA / project manager / developer) from their message signals.
The evidence behind every guess is returned (`evidence`) so a person can confirm or override it.
"""
from __future__ import annotations

import re
from collections import defaultdict

from app.intelligence.rules import signals

NAME_RULES = [
    (re.compile(r"\bsales\b", re.I), "SALES", 0.9),
    (re.compile(r"\bclient\b", re.I), "CLIENT", 0.85),
    (re.compile(r"\b(?:qa|tester|testing)\b", re.I), "QA", 0.85),
    (re.compile(r"\bdesign(?:er)?\b", re.I), "DESIGNER", 0.85),
    (re.compile(r"\b(?:pm|manager|lead)\b", re.I), "PROJECT_MANAGER", 0.8),
    (re.compile(r"\badmin\b", re.I), "ADMIN", 0.8),
    (re.compile(r"\b(?:frontend|front-end|fe)\b", re.I), "FRONTEND_DEVELOPER", 0.8),
    (re.compile(r"\b(?:backend|back-end|be)\b", re.I), "BACKEND_DEVELOPER", 0.8),
    (re.compile(r"^(?:mr|mrs|ms|dr)\.?\s", re.I), "CLIENT", 0.5),
]
CLIENT_SIDE = {"CLIENT", "CLIENT_REPRESENTATIVE"}

_I = re.I
# --- client-side behaviour (English / Hinglish / Devanagari Hindi) ---
REVIEW_REQUEST = re.compile(
    r"send me (?:the )?(?:link|screenshot|update|demo|video)|let me (?:see|check)|check (?:karke|kar ke|and (?:tell|let))|kitna kaam|"
    r"kaam .{0,25}(?:kahan|kaha|kahaan|where) tak|how (?:much|far) .{0,20}(?:work|done|progress)|status (?:bata|batao|kya)|"
    r"चेक करके|बताओ|बताइए|बताइये|कहा तक|कहाँ तक|कहां तक|दिखाओ|दिखाइए", _I)
COMPLAINT = re.compile(
    r"not (?:visible|showing|appearing|working|correct|coming|displayed)|doesn'?t (?:work|show)|nahi (?:dikh|dik|aa raha|chal|aaya)|nhi (?:dikh|dik|aa)|"
    r"\b(?:galat|wrong|incorrect)\b|नहीं (?:दिख|आ|चल|हो)|ठीक नहीं|गलत|समझा नहीं|दिख भी नहीं", _I)
AUTHORITY = re.compile(
    r"(?:hold|stop|pause|start|continue|resume) (?:this |the )?project|till i (?:won'?t )?approve|until i approve|i will approve|my approval|"
    r"approve (?:kar|karunga|karenge)|project (?:hold|rok|band)", _I)
PAID = re.compile(r"\b(?:paid|payment done|done payment|transferred|payment (?:kar|ho) (?:diya|gaya)|pay kar diya)\b|पेमेंट (?:कर|हो) (?:दिया|गया)", _I)
# --- delivery-side behaviour ---
PAY_REQUEST = re.compile(r"please pay|pay (?:asap|now|on this|\d)|\bqr\b|send (?:the )?(?:payment )?screenshot|payment (?:link|details)", _I)
ASK_DEPENDENCY = re.compile(
    r"we have (?:a few |some )?doubts|can we schedule a meeting|schedule (?:a )?meeting|share (?:the )?(?:credentials|keys?|logo|content)|"
    r"need (?:the )?(?:logo|content|keys?|credentials)|send (?:the )?(?:logo|content|images)", _I)
UPDATE_LIST = re.compile(r"(?:^|\n)\s*\d\s*[).]\s*\S.*(?:\n|\s)\s*\d\s*[).]\s*\S", _I)
UPDATE_WORD = re.compile(r"\b(?:today'?s? (?:work|update)|today update|daily update|update[:-])\b", _I)


def side_features(text: str) -> dict[str, int]:
    return {
        "review_request": int(bool(REVIEW_REQUEST.search(text))), "complaint": int(bool(COMPLAINT.search(text))),
        "authority": int(bool(AUTHORITY.search(text))), "paid": int(bool(PAID.search(text))),
        "pay_request": int(bool(PAY_REQUEST.search(text))), "ask_dependency": int(bool(ASK_DEPENDENCY.search(text))),
        "update_list": int(bool(UPDATE_LIST.search(text)) or bool(UPDATE_WORD.search(text) and re.search(r"\d\s*[).]", text))),
    }


def infer_roles(msgs, overrides: dict[str, str] | None = None, known_names=None) -> dict[str, dict]:
    overrides = overrides or {}
    names = list(known_names or dict.fromkeys(m.sender for m in msgs if m.sender))
    stats = defaultdict(lambda: defaultdict(int))
    for m in msgs:
        if not m.sender:
            continue
        s = signals(m.text)
        st = stats[m.sender]
        st["msgs"] += 1
        for k in ("done", "progress", "assign", "approval", "reject", "requirement", "bug", "test_pass", "deploy", "client_wait"):
            st[k] += int(s[k])
        for k, v in side_features(m.text).items():
            st[k] += v
    out = {}
    for n in names:
        if n in overrides:
            out[n] = {"role": overrides[n], "confidence": 1.0, "source": "admin"}
            continue
        hit = next(((r, c) for rx, r, c in NAME_RULES if rx.search(n)), None)
        if hit:
            out[n] = {"role": hit[0], "confidence": hit[1], "source": "name"}
            continue
        st = stats[n]
        work = st["done"] + st["progress"] + st["deploy"]
        client_score = st["review_request"] + st["complaint"] + 2 * st["authority"] + st["paid"]
        vendor_score = 2 * st["update_list"] + st["pay_request"] + st["ask_dependency"] + 0.5 * work
        ev = {"client_side": {k: st[k] for k in ("review_request", "complaint", "authority", "paid") if st[k]},
              "delivery_side": {k: st[k] for k in ("update_list", "pay_request", "ask_dependency", "done", "progress", "deploy") if st[k]},
              "client_score": client_score, "delivery_score": vendor_score, "messages": st["msgs"]}
        if client_score >= 2 and client_score > 1.2 * vendor_score:
            role, conf, src = "CLIENT", min(0.8, 0.45 + 0.05 * client_score), "behaviour"
        elif st["test_pass"] >= 2 and st["test_pass"] >= work:
            role, conf, src = "QA", 0.6, "behaviour"
        elif st["assign"] >= 3 and st["assign"] > work:
            role, conf, src = "PROJECT_MANAGER", 0.55, "behaviour"
        elif work >= 2 or st["update_list"] >= 1:
            role, conf, src = "DEVELOPER", 0.55 + (0.1 if st["update_list"] else 0), "behaviour"
        elif vendor_score >= 2 and client_score == 0:
            role, conf, src = "DEVELOPER", 0.4, "behaviour"      # delivery side (asks for payment/credentials/meetings) but little work talk
        elif (st["approval"] + st["requirement"] + st["reject"]) >= 1 and work == 0 and st["assign"] <= st["approval"] + st["requirement"] + st["reject"]:
            role, conf, src = "CLIENT", 0.4, "behaviour"
        else:
            role, conf, src = "OTHER", 0.3, "default"
        out[n] = {"role": role, "confidence": round(conf, 2), "source": src, "evidence": ev}
    return out
