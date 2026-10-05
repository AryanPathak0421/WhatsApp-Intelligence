"""Robust, streaming WhatsApp export parser (stdlib only).

Handles Android / iOS / US / locale variants, 12h + 24h clocks, multiline
messages, system / media / deleted messages, and never discards original text
(``raw_text`` keeps the message exactly as exported).
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator, Optional

# --- invisible characters WhatsApp / locales sprinkle into exports ----------
_INVISIBLE = dict.fromkeys(map(ord, "‎‏‪‫‬‭‮﻿"))
_SPACES = {ord(" "): " ", ord(" "): " ", ord(" "): " "}

_DATE = r"(?P<d1>\d{1,4})[/.\-](?P<d2>\d{1,2})[/.\-](?P<d3>\d{1,4})"
_TIME = (r"(?P<h>\d{1,2})[:.](?P<mi>\d{2})(?:[:.](?P<s>\d{2}))?"
         r"(?:\s?(?P<ampm>[APap]\.?\s?[Mm]\.?))?")
# [01/10/2026, 10:30 AM] Name: msg      (iOS)
_RE_BRACKET = re.compile(rf"^\[\s*{_DATE},?\s+{_TIME}\s*\]\s?(?P<rest>.*)$")
# 01/10/2026, 10:30 - Name: msg          (Android)
_RE_DASH = re.compile(rf"^{_DATE},?\s+{_TIME}\s+[-–—]\s?(?P<rest>.*)$")

_RE_SENDER = re.compile(r"^(?P<sender>[^:\n]{1,100}?):\s(?P<body>.*)$", re.S)
_RE_PHONE = re.compile(r"^~?\s?(\+?\d[\d\s\-()]{6,18}\d)$")
_RE_URL = re.compile(r"https?://[^\s<>\"']+|www\.[^\s<>\"']+", re.I)

_MEDIA_PATTERNS = [
    (re.compile(r"^<?\s*(image|photo)\s+omitted\s*>?$", re.I), "image"),
    (re.compile(r"^<?\s*video\s+omitted\s*>?$", re.I), "video"),
    (re.compile(r"^<?\s*audio\s+omitted\s*>?$", re.I), "audio"),
    (re.compile(r"^<?\s*sticker\s+omitted\s*>?$", re.I), "sticker"),
    (re.compile(r"^<?\s*gif\s+omitted\s*>?$", re.I), "gif"),
    (re.compile(r"^<?\s*document\s+omitted\s*>?$", re.I), "document"),
    (re.compile(r"^<?\s*media\s+omitted\s*>?$", re.I), "media"),
    (re.compile(r"^<attached:\s*(?P<f>.+?)>$", re.I), "attachment"),
    (re.compile(r"^(?P<f>.+?\.\w{2,5})\s+\(file attached\)$", re.I), "attachment"),
    (re.compile(r"^(?P<f>.+?\.\w{2,5})\s+•\s+\d+\s+pages?", re.I), "document"),
]
_RE_DELETED = re.compile(
    r"^(this message was deleted|you deleted this message|message deleted)\.?$", re.I)
_RE_EDITED = re.compile(r"\s*<This message was edited>\s*$", re.I)
_RE_FORWARDED = re.compile(r"^\s*forwarded(?: many times)?\s*\n?", re.I)

_SYSTEM_PATTERNS = [re.compile(p, re.I) for p in (
    r"messages and calls are end-to-end encrypted",
    r"\b(added|removed|left|joined|created group|changed the (subject|group|this group)|"
    r"changed (their|your) phone number|changed the group description|"
    r"changed this group's icon|deleted this group's icon|"
    r"you were added|you're now an admin|is now an admin|was added|"
    r"joined using this group's invite link|security code changed|"
    r"missed (voice|video) call|pinned a message|turned (on|off) disappearing messages|"
    r"started a (voice|video) call)\b",
)]


@dataclass
class ParsedMessage:
    index: int
    message_id: str
    timestamp: datetime
    sender_name: Optional[str]
    sender_phone: Optional[str]
    text: str                      # cleaned of edit/forward markers
    raw_text: str                  # EXACT original, incl. all lines (never altered)
    message_type: str              # text | media | system | deleted
    is_system: bool = False
    is_media: bool = False
    media_kind: Optional[str] = None
    is_deleted: bool = False
    is_edited: bool = False
    is_forwarded: bool = False
    urls: list[str] = field(default_factory=list)
    line_start: int = 0
    reply_context: Optional[str] = None  # exports carry no reply info


@dataclass
class ParseReport:
    total_lines: int = 0
    messages: int = 0
    skipped_preamble_lines: int = 0
    date_order: str = "DMY"            # DMY | MDY | YMD
    date_order_ambiguous: bool = False
    clock: str = "24h"                 # 24h | 12h
    header_style: str = "unknown"      # bracket | dash
    first_timestamp: Optional[datetime] = None
    last_timestamp: Optional[datetime] = None
    warnings: list[str] = field(default_factory=list)
    senders: Counter = field(default_factory=Counter)


class UnsupportedFormatError(ValueError):
    pass


def _clean_line(line: str) -> str:
    return line.rstrip("\r\n").translate(_INVISIBLE).translate(_SPACES)


def read_text_lines(path: str | Path) -> Iterator[str]:
    """Stream lines, auto-detecting common encodings (UTF-8/16, cp1252)."""
    p = Path(path)
    with p.open("rb") as fh:
        head = fh.read(4)
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        enc = "utf-16"
    else:
        enc = "utf-8-sig"
        try:  # cheap validity probe on first 1MB
            with p.open("rb") as fh:
                fh.read(1_000_000).decode("utf-8", errors="strict")
        except UnicodeDecodeError as e:
            # a probe cut mid-codepoint is fine; anything else is not UTF-8
            if e.start < 999_990:
                enc = "cp1252"
    with p.open("r", encoding=enc, errors="replace", newline=None) as fh:
        for line in fh:
            yield line


def _match_header(line: str):
    m = _RE_BRACKET.match(line)
    style = "bracket"
    if not m:
        m = _RE_DASH.match(line)
        style = "dash"
    return (m, style) if m else (None, None)


def detect_date_order(lines: Iterable[str], sample_limit: int = 20000) -> tuple[str, bool, str, str]:
    """Return (order, ambiguous, clock, style) by scanning header lines."""
    d1_gt12 = d2_gt12 = d1_4digit = 0
    seen = 0
    has_ampm = has_h_gt12 = False
    styles: Counter = Counter()
    for raw in lines:
        m, style = _match_header(_clean_line(raw))
        if not m:
            continue
        seen += 1
        styles[style] += 1
        a, b = m.group("d1"), int(m.group("d2"))
        if len(a) == 4:
            d1_4digit += 1
        elif int(a) > 12:
            d1_gt12 += 1
        if b > 12:
            d2_gt12 += 1
        if m.group("ampm"):
            has_ampm = True
        elif int(m.group("h")) > 12:
            has_h_gt12 = True
        if seen >= sample_limit:
            break
    clock = "12h" if has_ampm and not has_h_gt12 else "24h"
    style = styles.most_common(1)[0][0] if styles else "unknown"
    if d1_4digit:
        return "YMD", False, clock, style
    if d1_gt12 and not d2_gt12:
        return "DMY", False, clock, style
    if d2_gt12 and not d1_gt12:
        return "MDY", False, clock, style
    # ambiguous (all <=12) -> default to DMY (Indian locale), flag it
    return "DMY", True, clock, style


def _to_datetime(m: re.Match, order: str) -> datetime:
    a, b, c = m.group("d1"), m.group("d2"), m.group("d3")
    if order == "YMD":
        y, mo, d = int(a), int(b), int(c)
    elif order == "MDY":
        mo, d, y = int(a), int(b), int(c)
    else:
        d, mo, y = int(a), int(b), int(c)
    if y < 100:
        y += 2000
    h, mi, s = int(m.group("h")), int(m.group("mi")), int(m.group("s") or 0)
    ampm = m.group("ampm")
    if ampm:
        flag = ampm.lower().replace(".", "").replace(" ", "")
        if flag == "pm" and h < 12:
            h += 12
        elif flag == "am" and h == 12:
            h = 0
    return datetime(y, mo, d, h, mi, s)


def _classify(body: str) -> dict:
    """Derive flags from the body text (does not modify raw text)."""
    text = body
    info = dict(message_type="text", is_media=False, media_kind=None,
                is_deleted=False, is_edited=False, is_forwarded=False)
    tail = text.rstrip()
    if tail.lower().endswith("<this message was edited>"):   # plain endswith: a regex with \s* here is quadratic on long whitespace runs
        info["is_edited"] = True
        text = tail[: -len("<This message was edited>")].rstrip()
    fm = _RE_FORWARDED.match(text)
    if fm and len(text) > fm.end():
        info["is_forwarded"] = True
        text = text[fm.end():]
    stripped = text.strip()
    if _RE_DELETED.match(stripped):
        info.update(message_type="deleted", is_deleted=True)
    else:
        for pat, kind in _MEDIA_PATTERNS:
            if pat.match(stripped):
                info.update(message_type="media", is_media=True, media_kind=kind)
                break
    info["text"] = text.strip()
    return info


def _split_sender(rest: str) -> tuple[Optional[str], str]:
    m = _RE_SENDER.match(rest)
    if m:
        sender = m.group("sender")
        if len(sender.split()) <= 6 and not any(p.search(sender) for p in _SYSTEM_PATTERNS):
            return sender.strip(), m.group("body")
    return None, rest  # no "Name: " prefix -> system message


def _normalise_sender(name: str) -> tuple[str, Optional[str]]:
    name = name.strip().lstrip("~").strip()
    pm = _RE_PHONE.match(name)
    if pm:
        phone = re.sub(r"[^\d+]", "", pm.group(1))
        return name, phone
    return name, None


def _message_id(ts: datetime, sender: Optional[str], raw: str, dup: int) -> str:
    h = hashlib.sha1(f"{ts.isoformat()}|{sender or ''}|{raw}|{dup}".encode("utf-8"))
    return h.hexdigest()[:20]


class WhatsAppParser:
    """Usage::

        parser = WhatsAppParser()
        for msg in parser.parse_file("chat.txt"):
            ...
        parser.report  # stats, detected format, warnings
    """

    def __init__(self, date_order: Optional[str] = None):
        self.forced_order = date_order
        self.report = ParseReport()

    # -- public API ---------------------------------------------------------
    def parse_file(self, path: str | Path) -> Iterator[ParsedMessage]:
        order, amb, clock, style = detect_date_order(read_text_lines(path))
        yield from self._parse(read_text_lines(path), order, amb, clock, style)

    def parse_text(self, text: str) -> list[ParsedMessage]:
        lines = text.splitlines()
        order, amb, clock, style = detect_date_order(lines)
        return list(self._parse(lines, order, amb, clock, style))

    # -- internals ----------------------------------------------------------
    def _parse(self, lines: Iterable[str], order: str, amb: bool, clock: str,
               style: str) -> Iterator[ParsedMessage]:
        rep = self.report
        rep.date_order = self.forced_order or order
        rep.date_order_ambiguous = amb and not self.forced_order
        rep.clock, rep.header_style = clock, style
        if rep.date_order_ambiguous:
            rep.warnings.append("Date order ambiguous (all values <= 12); assumed DD/MM.")

        cur: Optional[dict] = None
        dup_counter: Counter = Counter()
        index = 0

        def flush() -> Optional[ParsedMessage]:
            nonlocal index
            if cur is None:
                return None
            raw = "\n".join(cur["lines"])
            sender_raw, body = cur["sender"], raw
            if sender_raw is None:
                info = dict(message_type="system", is_media=False, media_kind=None,
                            is_deleted=False, is_edited=False, is_forwarded=False,
                            text=body.strip())
                name = phone = None
            else:
                info = _classify(body)
                name, phone = _normalise_sender(sender_raw)
            key = (cur["ts"], name, raw)
            dup = dup_counter[key]
            dup_counter[key] += 1
            msg = ParsedMessage(
                index=index, message_id=_message_id(cur["ts"], name, raw, dup),
                timestamp=cur["ts"], sender_name=name, sender_phone=phone,
                text=info["text"], raw_text=raw, message_type=info["message_type"],
                is_system=sender_raw is None, is_media=info["is_media"],
                media_kind=info["media_kind"], is_deleted=info["is_deleted"],
                is_edited=info["is_edited"], is_forwarded=info["is_forwarded"],
                urls=_RE_URL.findall(info["text"]), line_start=cur["line_no"])
            index += 1
            rep.messages += 1
            if name:
                rep.senders[name] += 1
            rep.first_timestamp = rep.first_timestamp or msg.timestamp
            rep.last_timestamp = msg.timestamp
            return msg

        for line_no, raw_line in enumerate(lines, start=1):
            rep.total_lines = line_no
            line = _clean_line(raw_line)
            m, _ = _match_header(line)
            ts = None
            if m:
                try:
                    ts = _to_datetime(m, rep.date_order)
                except ValueError:
                    rep.warnings.append(f"line {line_no}: invalid date, treated as continuation")
            if ts is not None:
                done = flush()
                if done:
                    yield done
                sender, body = _split_sender(m.group("rest"))
                cur = {"ts": ts, "sender": sender, "lines": [body], "line_no": line_no}
            elif cur is not None:
                cur["lines"].append(line)
            else:
                if line.strip():
                    rep.skipped_preamble_lines += 1
        done = flush()
        if done:
            yield done
        if rep.messages == 0:
            raise UnsupportedFormatError(
                "No WhatsApp messages recognised. Is this a WhatsApp .txt export?")


def chat_fingerprint(path: str | Path) -> str:
    """SHA-256 of the file (duplicate-upload detection)."""
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
