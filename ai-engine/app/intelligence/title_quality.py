"""Is an extracted task title a usable task description, or a fragment of chat?

A task title becomes a row in the dashboard and counts toward progress. Fragments such as "I URL", "Join sir" or "I sub URL for" are not tasks: they carry no
object or action a person could do or verify, and each one that slips in (and later gets "completed" by an unrelated message) moves the headline percentage.
Rule: after removing placeholders (<url>, <media omitted>), @mentions, links, greetings/vocatives ("sir", "madam"), people's names and function words
(English and Hinglish), at least TWO content words must remain, the title must not be a short "I ..." / "we ..." remark, and it must not end on a
dangling connector ("... for", "... and"), which means the sentence was cut in the middle.
Deliberately conservative toward keeping real work: "Fix login", "Payment API integration", "Banner design banao" all pass.
"""
from __future__ import annotations

import re
from typing import Iterable

_FUNCTION_WORDS = frozenset("""
a an the of to in on for and or is are was were be been it its this that these those with as by at from into over under up down out off i we you he she they me my our your
their him her us them please pls plz ok okay yes no not also then so but if when what which who whom how why do does did done have has had will would can could should shall may
might must just only kindly ya yaar hi hello hey thanks thank thx
kar karo karna karni kare kiya kijiye dena dedo lena lo hai hain hoga hogi honge tha thi the ka ki ke ko se me mein par pe pr ye yeh wo woh yahan wahan abhi bhi hi toh to aur
na nahi nhi koi kuch sab ek bas fir phir jaise isko usko inko unko mujhe humko aap tum main mai hum
""".split())
_VOCATIVES = frozenset("sir madam mam maam bhai bro dear ji boss team guys everyone sirji".split())
_DANGLING = frozenset("for and to of with the in on at by or but if as".split())
_BIDI = re.compile("[\u200e\u200f\u202a-\u202e\u2066-\u2069]")                 # invisible direction marks that WhatsApp inserts
_MENTION = re.compile("@\u2068[^\u2069]*\u2069")                                    # a mention is wrapped in U+2068 ... U+2069
_STRIP = re.compile(r"<[^>]*>|https?://\S+|www\.\S+|@\S+")
_SPLIT = re.compile(r"[\s,;:.!?()\[\]{}\"'`/\\|+*=~^&%$#_-]+")
_SHORT_REMARK = re.compile(r"^\s*(?:i|we)\b", re.I)


def _tokens(text: str) -> list[str]:
    return [t for t in _SPLIT.split(_STRIP.sub(" ", _BIDI.sub("", _MENTION.sub(" ", text)))) if t]


def _counts(tok: str, names: set[str]) -> bool:
    low = tok.lower()
    if low in _FUNCTION_WORDS or low in _VOCATIVES or low in names or low.isdigit():
        return False
    # "UI", "DB", "QA", "ML" are real content; a lower-case two-letter word ("is", "ok", "pr") is not
    return len(low) >= 3 or bool(re.search(r"[ऀ-ॿ]", tok)) or (len(tok) == 2 and tok.isupper())


def title_usable(title: str, people: Iterable[str] = ()) -> bool:
    toks = _tokens(title)
    if not toks:
        return False
    names = {p.lower() for n in people for p in _tokens(n)}
    if sum(_counts(t, names) for t in toks) < 2:
        return False
    if _SHORT_REMARK.match(title) and len(toks) <= 4:
        return False
    if toks[-1].lower() in _DANGLING:
        return False
    return True
