"""Deadline / time extraction (English + Hinglish) with confidence.

Stores original text AND the normalised datetime relative to the MESSAGE time,
never to "now" (a chat imported later must resolve "Friday" against when it was said).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Optional

from app.intelligence.types import Deadline

WEEKDAYS = {"monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1, "wednesday": 2, "wed": 2,
            "thursday": 3, "thu": 3, "thur": 3, "thurs": 3, "friday": 4, "fri": 4, "saturday": 5, "sat": 5,
            "sunday": 6, "sun": 6, "somvar": 0, "mangalvar": 1, "budhvar": 2, "guruvar": 3, "shukravar": 4}
_WD = "|".join(sorted(WEEKDAYS, key=len, reverse=True))
EOB = 18  # default hour for date-only deadlines (end of business)

_TIME = re.compile(r"\b(?:by|at|before|till|tak|@)?\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm|baje)\b|\b([01]?\d|2[0-3]):([0-5]\d)\b", re.I)
_PATTERNS = [
    ("tomorrow", re.compile(r"\b(?:tomorrow|tmrw|tmr|kal(?: tak| subah| shaam)?)\b", re.I)),
    ("dayafter", re.compile(r"\b(?:day after tomorrow|parso(?:n)?(?: tak)?)\b", re.I)),
    ("today", re.compile(r"\b(?:today(?: eod)?|tonight|aaj(?: shaam| raat)?(?: tak)?|eod|end of (?:the )?day|cob)\b", re.I)),
    ("nextweek", re.compile(r"\b(?:next week|agle (?:hafte|week))\b", re.I)),
    ("thisweek", re.compile(r"\b(?:this week|end of (?:the )?week|eow|is hafte)\b", re.I)),
    ("weekday", re.compile(rf"\b(?:next |by |on |before )?({_WD})\b(?: tak)?", re.I)),
    ("inN", re.compile(r"\bin (\d{1,2}) (day|days|hour|hours|week|weeks)\b", re.I)),
    ("absdate", re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?(?:\s+|-)(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b|\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+(\d{1,2})(?:st|nd|rd|th)?\b", re.I)),
]
_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_DEADLINE_CTX = re.compile(r"\b(?:by|before|till|until|due|deadline|tak|ready by|needed by|deliver(?:y)? (?:date )?(?:is)?|submit)\b", re.I)


def _at(d: datetime, hour: int = EOB, minute: int = 0) -> datetime:
    return d.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _explicit_time(text: str) -> Optional[tuple[int, int]]:
    m = _TIME.search(text)
    if not m:
        return None
    if m.group(3):
        h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3).lower()
        if ap == "pm" and h < 12:
            h += 12
        if ap == "am" and h == 12:
            h = 0
        return (h, mi) if h < 24 else None
    return int(m.group(4)), int(m.group(5))


def extract_deadline(text: str, base: datetime) -> Optional[Deadline]:
    """Best deadline in text relative to ``base`` (message timestamp)."""
    ctx = bool(_DEADLINE_CTX.search(text))
    t = _explicit_time(text)
    for kind, rx in _PATTERNS:
        m = rx.search(text)
        if not m:
            continue
        raw = m.group(0).strip()
        conf = 0.85 if ctx else 0.6
        d: Optional[datetime] = None
        if kind == "tomorrow":
            d = _at(base + timedelta(days=1))
            if re.match(r"kal\b", raw, re.I) and "tak" not in raw.lower():
                conf -= 0.2  # 'kal' also means yesterday
        elif kind == "dayafter":
            d = _at(base + timedelta(days=2))
        elif kind == "today":
            d = _at(base)
            if re.search(r"shaam|eod|evening|tonight|cob|end of", raw, re.I):
                d = _at(base, EOB)
        elif kind == "nextweek":
            d = _at(base + timedelta(days=7 - base.weekday())); conf -= 0.2
        elif kind == "thisweek":
            d = _at(base + timedelta(days=(4 - base.weekday()) % 7)); conf -= 0.1
        elif kind == "weekday":
            wd = WEEKDAYS[m.group(1).lower()]
            delta = (wd - base.weekday()) % 7 or 7
            d = _at(base + timedelta(days=delta))
        elif kind == "inN":
            n, unit = int(m.group(1)), m.group(2).lower()
            d = base + (timedelta(hours=n) if unit.startswith("hour") else timedelta(days=n * (7 if unit.startswith("week") else 1)))
            conf = 0.8
        elif kind == "absdate":
            day = int(m.group(1) or m.group(4))
            mon = _MONTHS[(m.group(2) or m.group(3))[:3].lower()]
            year = base.year
            try:
                d = _at(datetime(year, mon, day))
                if d < base - timedelta(days=30):
                    d = _at(datetime(year + 1, mon, day))
            except ValueError:
                d = None
            conf = 0.9 if ctx else 0.7
        if d is None:
            continue
        if t and kind not in ("inN",):
            d = d.replace(hour=t[0], minute=t[1])
            conf = min(0.95, conf + 0.05)
        return Deadline(text=raw, when=d, confidence=round(max(0.3, min(conf, 0.95)), 2))
    # last resort: dateparser for things like "15/11" or "20 Nov"
    if ctx:
        try:
            import dateparser
            m = re.search(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b", text)
            if m:
                d = dateparser.parse(m.group(0), settings={"RELATIVE_BASE": base, "PREFER_DATES_FROM": "future",
                                                           "DATE_ORDER": "DMY"})
                if d:
                    return Deadline(text=m.group(0), when=_at(d), confidence=0.55)
        except Exception:  # dateparser is best-effort only
            pass
    return None
