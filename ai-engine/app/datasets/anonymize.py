"""Pseudonymise a WhatsApp export before it is shared with annotators or used as training data.

    python -m app.datasets.anonymize chat.txt chat.anon.txt --map chat.names.json

* senders -> "Person A", "Person B", ... (stable per run; the mapping file stays with the data owner and is NOT shared)
* every name part (first name and surnames) of a sender is replaced by the same pseudonym wherever it appears in messages
* system messages ("X added Y") are replaced by "<system message>"
* phone numbers, e-mail addresses, URLs, long digit strings (account / card / OTP-like) and pasted credentials (API keys, tokens, passwords) are masked
Roles written in the sender name ("Sales - Neha", "Anjali (Client)") are preserved as a suffix because the role engine uses them:
"Person C (Sales)", "Person D (Client)".

LIMITS: regexes cannot guarantee anonymity (free-text company names, addresses and unusual name spellings can remain). A human must spot-check
before data leaves the organisation.
"""
from __future__ import annotations

import argparse
import json
import re
import string
from pathlib import Path

from app.parsers.whatsapp import WhatsAppParser

PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
URL = re.compile(r"https?://\S+|www\.\S+", re.I)
# credentials pasted into chats: "SMS key ; fk64EXAM...", "password: xyz", "token=...", or any long mixed letter+digit blob
SECRET_AFTER = re.compile(r"(?i)\b(?P<label>api[ _-]?key|sms[ _-]?key|secret|token|password|passwd|passcode|pwd|pin|otp|key|user[ _-]?name|user[ _-]?id|login(?: id)?)\b"
                          r"(?P<sep>[ \t]*[:=;-]+[ \t]*|[ \t]+)(?P<val>\S{3,})")
_STRONG_LABEL = re.compile(r"(?i)^(?:password|passwd|passcode|pwd|user[ _-]?name|user[ _-]?id|login(?: id)?)$")
# a password-looking token: letters + digits + a special character, 8+ chars (e.g. "#abc@8779", "Abc!@#123")
SECRET_COMPLEX = re.compile(r"(?<![\w<])(?=\S{8,})(?=\S*[A-Za-z])(?=\S*\d)(?=\S*[!@#$%^&*])[^\s<>]+(?![\w>])")
SECRET_BLOB = re.compile(r"(?<![\w@])(?=[A-Za-z0-9_\-]{16,})(?=[^\s]*[A-Za-z])(?=[^\s]*\d)[A-Za-z0-9_\-]{16,}(?![\w@])(?!\.(?:jpe?g|png|gif|webp|mp4|opus|mp3|pdf|docx?|xlsx?|zip)\b)")
LONG_DIGITS = re.compile(r"\b\d{6,}\b")
# WhatsApp @mentions look like "@\u2068~Ayush Singh\u2069" (isolate marks + "~" for non-contacts) and often use a different name than the sender line
MENTION = re.compile(r"@[\u2066-\u2069]*~?\s*([^\u2066-\u2069\n@]{2,40}?)[\u2066-\u2069]+")
ROLE_HINT = re.compile(r"\b(sales|client|pm|qa|designer|admin)\b", re.I)


def _label(i: int) -> str:
    letters = string.ascii_uppercase
    return letters[i] if i < 26 else letters[i // 26 - 1] + letters[i % 26]


def _name_parts(sender: str) -> list[str]:
    base = re.sub(r"\(.*?\)|^(?:sales|pm|qa|dev)\s*[-|]\s*|^(?:mr|mrs|ms|dr)\.?\s+", "", sender, flags=re.I).strip()
    parts = [p for p in re.split(r"\s+", base) if len(p) >= 3 and p.isalpha()]
    return parts   # every name part (first + surnames), not only the first name


def _mask_labelled(m: re.Match) -> str:
    """"password :- X" / "User Id: X" / "token=abc123": mask the value. Plain prose ("password policy", "key feature") stays."""
    val, explicit, strong = m.group("val"), bool(re.search(r"[:=;-]", m.group("sep"))), bool(_STRONG_LABEL.match(m.group("label")))
    has_digit = bool(re.search(r"\d", val))
    if (strong and explicit) or (explicit and has_digit and len(val) >= 4) or (not explicit and has_digit and len(val) >= 6):
        return m.group(0)[:m.start("val") - m.start(0)] + "<secret>"
    return m.group(0)


def anonymize_text(text: str, redact: dict[str, str] | None = None, roles: dict[str, str] | None = None) -> tuple[str, dict]:
    """redact: extra {term: replacement} (companies, people who never speak). roles: {sender: "Client"|"Sales"|...} appended as a role hint."""
    redact = redact or {}
    roles = roles or {}
    msgs = WhatsAppParser().parse_text(text)
    senders = list(dict.fromkeys(m.sender_name for m in msgs if m.sender_name))
    mapping: dict[str, str] = {}
    for i, s in enumerate(senders):
        role = ROLE_HINT.search(s)
        hint = roles.get(s) or (role.group(1).title() if role else None)
        mapping[s] = f"Person {_label(i)}" + (f" ({hint})" if hint else "")
    name_map = {n: mapping[s].split(" (")[0] for s in senders for n in _name_parts(s)}

    mentions: dict[str, str] = {}

    def mention(m: re.Match) -> str:
        key = m.group(1).strip().lower()
        known = next((alias for n, alias in name_map.items() if n.lower() in key.split()), None)   # same person as a sender
        return "@" + (known or mentions.setdefault(key, f"Mention {len(mentions) + 1}"))

    def scrub(t: str) -> str:
        t = MENTION.sub(mention, t)
        for term, alias in sorted(redact.items(), key=lambda kv: -len(kv[0])):
            t = re.sub(re.escape(term), alias, t, flags=re.I)
        t = EMAIL.sub("<email>", URL.sub("<url>", t))
        t = SECRET_AFTER.sub(_mask_labelled, t)
        t = SECRET_COMPLEX.sub("<secret>", t)
        t = SECRET_BLOB.sub("<secret>", t)
        t = PHONE.sub("<phone>", t)
        t = LONG_DIGITS.sub("<number>", t)
        for name, alias in sorted(name_map.items(), key=lambda kv: -len(kv[0])):
            t = re.sub(rf"(?<!\w){re.escape(name)}(?!\w)", alias, t, flags=re.I)
        return t

    out = []
    for m in msgs:
        head = m.timestamp.strftime("%d/%m/%Y, %H:%M")
        if m.is_system:   # "X added Y", "changed the subject to ..." carry names/numbers we cannot map: drop the content entirely
            out.append(f"{head} - <system message>")
        else:
            body = scrub(m.text)
            out.append(f"{head} - {mapping[m.sender_name]}: {body}")
    return "\n".join(out) + "\n", {"senders": mapping, "name_parts": name_map}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("dst"); ap.add_argument("--map", help="write the pseudonym mapping here (keep private)")
    ap.add_argument("--redact", action="append", default=[], metavar="TERM=ALIAS", help="extra term to replace (repeatable), e.g. 'Acme Ltd=ClientCo'")
    ap.add_argument("--role", action="append", default=[], metavar="SENDER=ROLE", help="role hint appended to a sender, e.g. 'Rahul=Client' (repeatable)")
    a = ap.parse_args(argv)
    kv = lambda items: dict(i.split("=", 1) for i in items)  # noqa: E731
    text, mapping = anonymize_text(Path(a.src).read_text(encoding="utf-8-sig"), kv(a.redact), kv(a.role))
    Path(a.dst).write_text(text, encoding="utf-8")
    if a.map:
        Path(a.map).write_text(json.dumps(mapping, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {a.dst}" + (f" and private mapping {a.map}" if a.map else " (no mapping saved: irreversible)"))


if __name__ == "__main__":
    main()
