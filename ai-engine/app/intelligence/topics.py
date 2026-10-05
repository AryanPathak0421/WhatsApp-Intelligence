"""Topic extraction: content tokens + alias groups, task titles, assignee detection."""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Iterable, Optional

from app.intelligence.rules import norm

STOP = set("""a an the to of in on for by at is are was were be been it this that these those and or but with from as
please pls plz kindly can could you we i he she they them our your my me us will would should shall do does did done
have has had not no yes ok okay hi hello hey team sir bhai ji hai hain ho hu hum ka ki ke ko se me mein par pe ne
tak aur bhi kar karo kiya kr diya gaya gya raha rahi abhi ab kal aaj today tomorrow now soon asap
new just also still yet any all some one up out about regarding client sales
monday tuesday wednesday thursday friday saturday sunday eod morning evening shaam subah
completed complete finished working work started pending ready live deployed fixed tested testing
hasn hasnt haven didn don isn wasn t s ll update status waiting need needs want wants wanted get got make made take took give gave""".split())

ALIASES = {  # alias group -> member tokens (synonyms across EN / Hinglish / product names)
    "payment": {"payment", "payments", "razorpay", "stripe", "payu", "paypal", "cashfree", "gateway", "upi", "checkout", "billing"},
    "auth": {"login", "signin", "signup", "otp", "auth", "authentication", "password", "register", "registration"},
    "admin": {"admin", "dashboard", "panel"},
    "notify": {"notification", "notifications", "push", "fcm", "email", "sms"},
    "design": {"design", "ui", "ux", "mockup", "mockups", "wireframe", "wireframes", "figma", "banner", "layout"},
    "deploy": {"deploy", "deployment", "production", "server", "release", "hosting", "devops", "ci", "cd", "pipeline"},
    "db": {"database", "db", "migration", "schema", "sql", "postgres", "mongodb"},
    "search": {"search", "filter", "filters", "sort"},
    "cart": {"cart", "basket", "wishlist", "order", "orders", "tracking"},
    "doc": {"docs", "documentation", "document", "readme"},
    "invoice": {"invoice", "invoices", "pdf", "report", "export"},
    "api": {"api", "apis", "endpoint", "backend"},
}
_TOKEN2GROUP = {t: g for g, ts in ALIASES.items() for t in ts}
STEM_RX = re.compile(r"(ing|ed|es|s)$")

_TASK_VERBS = re.compile(
    r"\b(?:integrate|integration of|work on|working on|take up|pick up|build|implement|set up|setup|create|write|handle|"
    r"fix|design|develop|add|update|prepare|deploy|migrate|test|complete|finish|start|send|share|submit|review|check|do)\b\s+(?:the |a |an )?(.+)", re.I)
_TITLE_CUT = re.compile(r"\b(?:by|before|till|until|tak|asap|today|tomorrow|kal|aaj|on|this|next|monday|tuesday|wednesday|thursday|friday|saturday|sunday|eod)\b|[,.;!?]|\bplease\b", re.I)


def stem(w: str) -> str:
    return STEM_RX.sub("", w) if len(w) > 4 else w


def tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9ऀ-ॿ]+", norm(text)) if w not in STOP and len(w) > 1]


def topic_set(text: str, extra_stop: Iterable[str] = ()) -> frozenset:
    return _topic_set(text, tuple(sorted({e.lower() for e in extra_stop})))


@lru_cache(maxsize=200_000)
def _topic_set(text: str, extra: tuple) -> frozenset:
    ex = set(extra)
    out = set()
    for w in tokens(text):
        if w in ex:
            continue
        out.add(stem(w))
        g = _TOKEN2GROUP.get(w) or _TOKEN2GROUP.get(stem(w))
        if g:
            out.add("@" + g)
    return frozenset(out)


@lru_cache(maxsize=100_000)
def _split(s: frozenset) -> tuple[frozenset, frozenset]:
    g = frozenset(x for x in s if x[0] == "@")
    return g, s - g


def topic_overlap(a: frozenset, b: frozenset) -> float:
    """Weighted overlap in [0,1]; alias-group matches count even when words differ."""
    if not a or not b:
        return 0.0
    ga, wa = _split(a)
    gb, wb = _split(b)
    group = len(ga & gb) / max(1, min(len(ga), len(gb))) if ga and gb else 0.0
    word = len(wa & wb) / max(1, min(len(wa), len(wb))) if wa and wb else 0.0
    return min(1.0, 0.6 * max(group, word) + 0.4 * min(group, word) + (0.0 if max(group, word) == 0 else 0.15))


def make_title(text: str, people: Iterable[str] = ()) -> str:
    t = text.strip()
    for p in sorted(people, key=len, reverse=True):
        t = re.sub(rf"^\s*{re.escape(p.split()[-1] if ' - ' in p else p)}\b[\s,:-]*", "", t, flags=re.I)
        t = re.sub(rf"\b{re.escape(p)}\b", "", t, flags=re.I)
    t = re.sub(r"(?<!\w)(?:please|pls|plz|kindly)(?!\w)[\s,]*", "", t, flags=re.I).strip()
    m = _TASK_VERBS.search(t)
    chunk = m.group(1) if m else t
    chunk = _TITLE_CUT.split(chunk)[0]
    if m and m.group(0).lower().startswith("integrate") and "integration" not in chunk.lower():
        chunk = chunk.strip() + " integration"
    chunk = re.sub(r"\b(?:can you|could you|kindly|please|pls|need(?:s)? it|need|assigning|assign|to)\b", "", chunk, flags=re.I)
    chunk = re.sub(r"(?<!\w)(?:banana hai|banani hai|karna hai|karni hai|kar dena|kar do|kar lo|karo|dekh lena|dekh lo|assign kiya hai|banao|bana do|bana dena|bhej do|bhejo|kar dijiye|kijiye|dijiye)(?!\w)", "", chunk, flags=re.I)
    chunk = re.sub(r"\s+", " ", chunk).strip(" -:,.")
    if not chunk or len(chunk) < 3:  # Hinglish order "<task> <deadline> kar dena"
        chunk = _TITLE_CUT.split(re.sub(r"\b(?:kar dena|kar do|kar lo|karo|dekh lena|dekh lo|assign kiya hai|banao|bana do|bana dena|bhej do|bhejo|kar dijiye|kijiye|dijiye)\b", "", t, flags=re.I))[0].strip(" -:,.")
        chunk = re.sub(r"\b(?:please|par kaam shuru)\b", "", chunk, flags=re.I).strip()
    return chunk[:120]


def find_people(text: str, names: Iterable[str]) -> list[str]:
    """Known participant names mentioned in text (first-name match, case-insensitive)."""
    found = []
    low = norm(text)
    for n in names:
        if _name_rx(n).search(low):
            found.append(n)
    return found


@lru_cache(maxsize=4096)
def _name_rx(n: str) -> re.Pattern:
    keys = {norm(n)}
    short = re.sub(r"\(.*?\)|^(?:sales|pm|qa|dev)\s*-\s*|^(?:mr|mrs|ms|dr)\.?\s+", "", n, flags=re.I).strip()
    if short:
        keys.add(norm(short))
        keys.add(norm(short.split()[0]))
    alts = "|".join(re.escape(k) for k in sorted(keys, key=len, reverse=True) if k)
    return re.compile(rf"(?<!\w)(?:{alts})(?!\w)") if alts else re.compile(r"(?!x)x")


@lru_cache(maxsize=4096)
def _vocative_rx(n: str) -> Optional[re.Pattern]:
    first = norm(re.sub(r"\(.*?\)|^(?:sales|pm|qa|dev)\s*-\s*|^(?:mr|mrs|ms|dr)\.?\s+", "", n, flags=re.I).split()[0] if n.split() else n)
    return re.compile(rf"(?:^|[.!?\n]\s*|,\s+)@?{re.escape(first)}\b[\s,:-]") if first else None   # at the start of any sentence / clause


def vocative_target(text: str, names: Iterable[str]) -> Optional[str]:
    """'Amit, please ...' / 'Amit please ...' / '... can you Amit' -> Amit."""
    low = norm(text)
    for n in names:
        rx = _vocative_rx(n)
        if rx is not None and rx.search(low):
            return n
    return None


def sentence_from(text: str, name: str) -> str:
    """The part of a multi-sentence message that starts at the addressed person ("Understood Dr. Rao. Tushar, do X by Friday" -> "Tushar, do X by Friday")."""
    rx = _vocative_rx(name)
    m = rx.search(norm(text)) if rx else None
    if not m:
        return text
    first = re.escape(name.split()[0].lstrip("@"))
    hit = re.search(rf"(?:^|[.!?\n]\s*|,\s+)(@?{first}\b.*)$", text, re.I | re.S)
    return hit.group(1) if hit else text
