"""Requirement versioning + change detection (e.g. Stripe -> Razorpay)."""
from __future__ import annotations

import hashlib
import re
from typing import Optional

from app.intelligence.rules import norm, signals
from app.intelligence.topics import ALIASES, topic_set
from app.intelligence.types import ENGINE_VERSION, Msg

CHOICE_GROUPS = {
    "payment-provider": ["razorpay", "stripe", "payu", "paypal", "cashfree", "paytm"],
    "database": ["postgresql", "postgres", "mysql", "mongodb", "sqlite", "firebase"],
    "mobile-framework": ["react native", "flutter", "kotlin", "swift", "ionic"],
    "otp-channel": ["whatsapp otp", "sms otp", "email otp"],
    "login-method": ["phone", "email", "google", "facebook"],
    "cloud": ["aws", "azure", "gcp", "digitalocean", "heroku", "vercel"],
}
INSTEAD = re.compile(r"(.+?)\s+(?:instead of|in place of|rather than)\s+(.+)", re.I)
JAGAH = re.compile(r"(.+?)\s+ki jagah\s+(.+)", re.I)
USE = re.compile(r"\b(?:use|using|go with|going with|wants?|chahiye|prefer|via|switch(?:ing)? to|shift(?:ing)? to|move to)\b", re.I)


_CHOICE_RX = {(g, o): re.compile(rf"(?<!\w){re.escape(o)}(?!\w)") for g, opts in CHOICE_GROUPS.items() for o in opts}
_ANY_CHOICE = re.compile("|".join(sorted((re.escape(o) for opts in CHOICE_GROUPS.values() for o in opts), key=len, reverse=True)))


def _find_choice(text: str) -> list[tuple[str, str, int]]:
    low = norm(text)
    if not _ANY_CHOICE.search(low):      # fast reject: most messages mention no option at all
        return []
    hits = []
    for (g, o), rx in _CHOICE_RX.items():
        for m in rx.finditer(low):
            hits.append((g, o, m.start()))
    return sorted(hits, key=lambda x: x[2])


def detect_requirements(msgs: list[Msg], roles: dict):
    """Return (requirements, changes). requirements: key -> {versions:[...]} ."""
    reqs: dict[str, dict] = {}
    changes: list[dict] = []

    def record(key, value, old, by, m, conf, impact, change):
        r = reqs.setdefault(key, {"key": key, "versions": [], "impact": impact})
        ver = len(r["versions"]) + 1
        r["versions"].append({"version": ver, "value": value, "old_value": old, "changed_by": by,
                              "changed_at": m.ts, "message_id": m.id, "confidence": round(conf, 2)})
        if change:
            changes.append({"id": "rc_" + hashlib.sha1((m.id + key).encode()).hexdigest()[:10], "key": key,
                            "old_value": old, "new_value": value, "changed_by": by,
                            "changed_by_role": roles.get(by, {}).get("role"), "impact": impact,
                            "changed_at": m.ts, "confidence": round(conf, 2), "source_message_ids": [m.id],
                            "version": ver, "needs_review": conf < 0.7, "model_version": ENGINE_VERSION})

    for m in msgs:
        if not m.sender:
            continue
        s = signals(m.text)
        choices = _find_choice(m.text)
        is_change = s["req_change"] or (m.category == "REQUIREMENT_CHANGE" and m.cat_conf >= 0.6)
        is_req = s["requirement"] or (m.category == "REQUIREMENT" and m.cat_conf >= 0.6)
        if choices and not s["question"] and USE.search(m.text) and not (s["done"] or s["progress"]):
            is_req = True
        if not (is_change or (is_req and choices)):
            continue
        by = m.sender
        impact = next((g for g, ts in ((g, ALIASES.get(g, ())) for g in ALIASES) if any(t in norm(m.text).split() for t in ts)), None)
        groups = {c[0] for c in choices}
        if choices:
            g = choices[0][0]
            mentions = [c for c in choices if c[0] == g]
            vals = list(dict.fromkeys(c[1] for c in mentions))
            current = reqs.get(g, {}).get("versions", [{}])[-1].get("value")
            new = old = None
            conf = 0.5
            if is_change and len(vals) >= 2:
                im, jm = INSTEAD.search(m.text), JAGAH.search(m.text)
                if im:
                    new = next((v for v in vals if v in norm(im.group(1))), vals[0]); old = next((v for v in vals if v in norm(im.group(2))), vals[1])
                elif jm:
                    old = next((v for v in vals if v in norm(jm.group(1))), vals[0]); new = next((v for v in vals if v in norm(jm.group(2))), vals[1])
                else:
                    old, new = vals[0], vals[-1]
                conf = 0.85
            elif len(vals) >= 1:
                new = vals[-1] if len(vals) == 1 else vals[0]
                old = current if current and current != new else None
                conf = 0.75 if (is_change and old) else 0.6
            if new is not None and new == current and is_change and old and old != new:
                # explicit "X instead of Y" restating the value we already hold: report it, no new version
                changes.append({"id": "rc_" + hashlib.sha1((m.id + g).encode()).hexdigest()[:10], "key": g,
                                "old_value": old, "new_value": new, "changed_by": by,
                                "changed_by_role": roles.get(by, {}).get("role"), "impact": impact or g,
                                "changed_at": m.ts, "confidence": 0.6, "source_message_ids": [m.id],
                                "version": len(reqs[g]["versions"]), "needs_review": True, "reaffirmation": True,
                                "model_version": ENGINE_VERSION})
                continue
            if new is None or new == current:
                continue
            record(g, new, old or current, by, m, conf, impact or g, change=bool(is_change and (old or current)))
            if not is_change:
                pass
        elif is_change and (INSTEAD.search(m.text) or JAGAH.search(m.text)):
            # "we need WhatsApp reminders instead of SMS reminders": no known option list, but the sentence names both sides
            im = INSTEAD.search(m.text)
            if im:
                new, old = im.group(1), im.group(2)
            else:
                jm = JAGAH.search(m.text)
                old, new = jm.group(1), jm.group(2)
            new = re.sub(r"^.*\b(?:need|needs|want|wants|use|using|chahiye|prefer|switch to)\b\s*", "", new, flags=re.I).strip(" .,-:!")
            old = re.sub(r"\s+(?:for|ke liye|chahiye|hi|please)\b.*$", "", old, flags=re.I).strip(" .,-:!")
            key = "general:" + hashlib.sha1("|".join(sorted(topic_set(old))).encode()).hexdigest()[:8]
            record(key, new[:200], old[:200], by, m, 0.65, impact, change=True)
        elif is_change:
            key = "general:" + hashlib.sha1("|".join(sorted(topic_set(m.text, ("client",)))).encode()).hexdigest()[:8]
            record(key, m.text.strip()[:200], None, by, m, 0.5, impact, change=True)
    return list(reqs.values()), changes
