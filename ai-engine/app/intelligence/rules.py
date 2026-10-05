"""Bilingual (English / Hinglish / some Devanagari) signal lexicon.

Deliberately high-precision. The classifier supplies recall; these rules supply
evidence the status/conflict engines can reason over. Not claimed accurate until
evaluated on real labelled chats.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

_I = re.I


@lru_cache(maxsize=200_000)
def norm(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).lower()
    return re.sub(r"\s+", " ", t).strip()


def _rx(*parts: str) -> re.Pattern:
    return re.compile(r"(?<!\w)(?:" + "|".join(parts) + r")(?!\w)", _I)


DONE = _rx(r"done", r"completed?", r"integrated", r"built", r"developed", r"configured", r"shipped", r"is ready and merged", r"finished", r"implemented", r"fixed", r"deployed", r"merged",
           r"resolved", r"wrapped up", r"sorted", r"patched", r"delivered", r"is live", r"are live", r"live on (?:staging|prod\w*)", r"went live",
           r"ho gaya", r"ho gya", r"hogaya", r"kar diya", r"kr diya", r"kar di", r"complete ho",
           r"live ho", r"deploy ho", r"push kar diya", r"पूरा हो गया", r"हो गया",
           r"ho ?(?:gye|gaye|gayi|gai|gae) h(?:ai|ain)?", r"hog(?:ye|aye|ayi) h(?:ai|ain)?", r"ho rhe h(?:ai|ain)?", r"हो गए", r"हो गई")
WEAK_DONE = _rx(r"ready", r"working now", r"working fine", r"(?:is|are) working", r"ready hai", r"chal raha hai", r"chal gaya", r"went through")
NEGATION = re.compile(
    r"(not|n't|never|yet to|still to|to do|not yet|haven't|hasn't|nahi|nhi|nahin|baaki|abhi tak|pending|"
    r"incomplete|unfinished|not started)", _I)
PROGRESS = _rx(r"working on", r"in progress", r"wip", r"started", r"currently (?:working|developing)",
               r"developing", r"coding", r"half way", r"halfway", r"kaam chal raha", r"par kaam chal",
               r"laga hu", r"lga hu", r"bana raha", r"bana rahi", r"kar raha hu", r"kar rahi hu",
               r"शुरू", r"काम चल रहा")
BLOCKED = _rx(r"blocked", r"stuck", r"can'?t (?:proceed|move ahead|continue)", r"cannot proceed",
              r"unable to proceed", r"atka", r"aage nahi badh", r"nahi mile", r"nahi mila", r"not received",
              r"dependency", r"waiting for (?!client)", r"no access", r"access nahi")
CLIENT_WAIT = _rx(r"waiting for (?:the )?client", r"waiting on (?:the )?client", r"awaiting client",
                  r"client (?:has not|hasn'?t|have not|haven'?t|did not|didn'?t) (?:shared|sent|responded|replied|confirmed|approved|given|provided)",
                  r"client (?:response|reply|approval|confirmation|feedback|credentials?) (?:is )?(?:still )?pending",
                  r"pending (?:from|with) (?:the )?client", r"from (?:the )?client (?:is )?pending",
                  r"client ka (?:response|reply|approval|confirmation) .{0,15}pending",
                  r"client (?:ne|se) .{0,40}(?:nahi|nhi)\b", r"(?:approval|sign-?off|uat|credentials?|content) .{0,20}pending",
                  r"still waiting for the client", r"haven'?t heard back from (?:the )?client",
                  r"client (?:to|needs to|need to) (?:confirm|send|share|approve|provide)",
                  r"need(?:s|ed)?\b.{0,30}?\bfrom (?:the )?client", r"client se .{0,50}(?:confirm|bhej|share|lena|karna padega|chahiye)", r"client confirmation (?:required|needed)",
                  r"क्लाइंट का जवाब")
APPROVAL = _rx(r"approved?", r"approve kar", r"green signal", r"looks good", r"sign-?off (?:done|given)",
               r"go ahead", r"happy with", r"pasand aaya", r"accepted", r"confirmed by client")
REJECT = _rx(r"rejected", r"not approved", r"don'?t like", r"pasand nahi", r"not happy", r"hasn'?t approved",
             r"approve nahi", r"approval pending")
TEST_PASS = _rx(r"tested successfully", r"test(?:ing)? (?:complete|done|passed)", r"qa pass", r"all green",
                r"all tests pass(?:ed)?", r"test ho gaya", r"testing ho gaya", r"test kar liya", r"sab pass",
                r"working as expected", r"verified")
DEPLOY = _rx(r"deployed", r"deploy ho", r"pushed (?:the )?(?:new )?build to (?:production|prod)", r"released?",
             r"is live", r"went live", r"live ho", r"production (?:pe|par|me)", r"on production(?! deploy)", r"to production")
BUG = _rx(r"bug", r"crash(?:es|ed|ing)?", r"not working", r"error", r"fails?", r"failing", r"broken", r"issue",
          r"galat", r"kaam nahi kar", r"nahi chal", r"not loading", r"500")
BUG_FIXED = _rx(r"fixed", r"resolved", r"sorted", r"patched", r"solve ho gaya", r"theek kar diya", r"fix kar diya",
                r"fix ho gaya", r"(?:no longer|not) reproducible(?: anymore)?", r"(?:can'?t|cannot|unable to) reproduce", r"ab nahi aa raha")
REOPEN = _rx(r"reopen(?:ed)?", r"still (?:failing|broken|not working|crash\w*)", r"again (?:failing|broken)",
             r"phir se", r"dobara")
ASSIGN = _rx(r"please", r"pls", r"plz", r"can you", r"could you", r"kindly", r"assign(?:ing|ed)?", r"kar dena",
             r"karo", r"dekh lena", r"pick up", r"take up", r"handle", r"need(?:s)? (?:you )?to", r"i need",
             r"banao", r"dekh lo", r"kar lo", r"bhej do", r"bhejo", r"dekhna", r"bana do", r"bana dena", r"kar dijiye", r"kijiye", r"dijiye", r"banana hai", r"banani hai", r"karna hai", r"karni hai", r"kar do", r"shuru karo", r"need someone", r"you will")
COMMIT = _rx(r"i will", r"i'?ll", r"will (?:send|share|deploy|finish|complete|push|fix|update|check|do)",
             r"kar dunga", r"kar dungi", r"(?:kar|kr) (?:denge|dege|dete h(?:ai)?|dete hain)", r"(?:krte|karte) h(?:ai|ain)? (?:fir|then|kal)", r"kal (?:tak )?(?:kar|kr) (?:dunga|dungi|denge)", r"bhej dunga", r"bhej dungi", r"de dunga", r"kar dete hain",
             r"will do", r"by (?:eod|tomorrow|today)")
REQ_CHANGE = _rx(r"instead of", r"in place of", r"ki jagah", r"changed (?:their|his|her) mind", r"now wants?",
                 r"scope change", r"naya (?:scope|requirement)", r"requirement (?:has )?changed",
                 r"ab .{0,20}chahiye", r"change(?:d)? (?:the )?requirement", r"actually (?:client|they) want")
REQUIREMENT = _rx(r"requirement", r"dena h(?:ai)?", r"add (?:kr|kar)(?:na| do| dena| denge)?", r"option (?:de|dena)", r"should support", r"should be able", r"must (?:be able|support|have)",
                  r"need(?:s)? to support", r"chahta hai ki", r"chahiye", r"we need", r"client wants")
DECISION = _rx(r"decided", r"decision", r"finali[sz]ed", r"final:", r"(?<=\w)\W{1,2}final", r"\bfinal\b(?!ly)", r"agreed", r"we will (?:use|go with|drop)",
               r"confirm kiya", r"decide hua", r"hum .{0,20}(?:use|karenge)")
MEETING = _rx(r"meeting", r"call", r"demo", r"sprint planning", r"standup", r"stand-up", r"catch ?up", r"sync")
RISK = _rx(r"risk", r"miss(?:ed)? the (?:launch|deadline|release)", r"delay(?:ed|s)?", r"tight", r"late ho",
           r"may slip", r"might slip", r"won'?t make it", r"time pe nahi", r"over budget", r"may exceed")
PAYMENT = _rx(r"payment", r"invoice", r"advance", r"milestone", r"paid", r"transfer(?:red)?", r"overdue", r"pay (?:asap|now|\d)", r"\d[\d,.]*k? ?(?:rs|inr|rupees?)", r"(?:rs\.?|inr|₹) ?\d[\d,.]*", r"पेमेंट", r"भुगतान")
QUESTION = re.compile(r"\?\s*$|^(?:kya|what|when|who|how|why|where|did|is|are|any update)\b"
                      r"|\b(?:kya|kitna|kitni|kaise|kab|kaun|kyun|kyu)\b|\bho (?:sakta|sakti) h(?:ai)?\b|\bor not\W*$|क्या|कितना|कैसे|कब\b", _I)

BUG_SOFT_EXCLUDE = re.compile(r"\b(?:no|zero|without|nahi mila) (?:bug|issue|error)s?\b", _I)

CLIENT_PENDING_TYPES = [
    ("CREDENTIALS", _rx(r"credentials?", r"(?:api |sandbox |secret )?keys?", r"tokens?", r"access", r"password", r"login details", r"account details", r"sandbox", r"hosting")),
    ("APPROVAL", _rx(r"approval", r"approved?", r"approve", r"sign-?off", r"confirmation", r"confirm", r"green signal")),
    ("UAT", _rx(r"uat")),
    ("PAYMENT", _rx(r"payment", r"invoice", r"advance", r"milestone")),
    ("CONTENT", _rx(r"content", r"logo", r"images?", r"photos?", r"files?", r"assets?", r"copy", r"text")),
    ("FEEDBACK", _rx(r"feedback", r"review", r"response", r"reply")),
    ("REQUIREMENT", _rx(r"requirements?", r"clarification", r"scope")),
]


def has_done(text: str) -> tuple[bool, bool]:
    """Return (done, negated). Negation window: 30 chars before / 18 after the match."""
    t = norm(text)
    done = False
    neg = False
    for m in DONE.finditer(t):
        before = t[max(0, m.start() - 30):m.start()]
        after = t[m.end():m.end() + 18]
        if NEGATION.search(before) or re.search(r"\b(?:nahi|nhi|not yet|yet)\b", after):
            neg = True
        else:
            done = True
    if not done and NEGATION.search(t) and not DONE.search(t):
        neg = bool(re.search(r"\b(?:not|yet to|haven't|hasn't|nahi|nhi|baaki|not started|still to do)\b", t))
    return done, neg


@lru_cache(maxsize=200_000)
def signals(text: str) -> dict[str, bool]:
    """Cached per text (every engine asks for the same message). Treat the returned dict as read-only."""
    t = norm(text)
    done, neg_done = has_done(text)
    blocked = bool(BLOCKED.search(t))
    s = {
        "done": done, "neg_done": neg_done, "weak_done": bool(WEAK_DONE.search(t)),
        "progress": bool(PROGRESS.search(t)), "blocked": blocked,
        "client_wait": bool(CLIENT_WAIT.search(t)),
        "approval": bool(APPROVAL.search(t)) and not REJECT.search(t),
        "reject": bool(REJECT.search(t)),
        "test_pass": bool(TEST_PASS.search(t)), "deploy": bool(DEPLOY.search(t)),
        "bug": bool(BUG.search(t)) and not BUG_SOFT_EXCLUDE.search(t),
        "bug_fixed": bool(BUG_FIXED.search(t)), "reopen": bool(REOPEN.search(t)),
        "assign": bool(ASSIGN.search(t)), "commit": bool(COMMIT.search(t)),
        "req_change": bool(REQ_CHANGE.search(t)), "requirement": bool(REQUIREMENT.search(t)),
        "decision": bool(DECISION.search(t)), "meeting": bool(MEETING.search(t)),
        "risk": bool(RISK.search(t)), "payment": bool(PAYMENT.search(t)),
        "question": bool(QUESTION.search(t)),
    }
    return s


def client_pending_type(text: str) -> str:
    t = norm(text)
    for name, rx in CLIENT_PENDING_TYPES:
        if rx.search(t):
            return name
    return "OTHER"
