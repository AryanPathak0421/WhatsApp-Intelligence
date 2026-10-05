"""Robustness: hostile / malformed input must never crash the parser or the engines, and must not hang (ReDoS)."""
import random
import string
import time

import pytest

from app.intelligence.pipeline import analyze
from app.intelligence.rules import signals
from app.intelligence.temporal import extract_deadline
from app.intelligence.types import Msg
from app.parsers.whatsapp import UnsupportedFormatError, WhatsAppParser

HEADER = "01/10/2026, 10:{m:02d} - {s}: {t}\n"
ALPHABET = string.printable + "ऀअआक्षत्र😀👍‎ \u0000﻿"


def chat_of(texts, sender="Amit"):
    return "".join(HEADER.format(m=i % 60, s=sender, t=t) for i, t in enumerate(texts))


def run(text):
    parsed = WhatsAppParser().parse_text(text)
    return analyze([Msg.from_parsed(m) for m in parsed])


def test_random_garbage_never_crashes_parser():
    rng = random.Random(7)
    for _ in range(300):
        blob = "".join(rng.choice(ALPHABET) for _ in range(rng.randint(0, 400)))
        try:
            WhatsAppParser().parse_text(blob)
        except UnsupportedFormatError:
            pass  # the only acceptable failure


def test_random_message_bodies_never_crash_analysis():
    rng = random.Random(11)
    bodies = ["".join(rng.choice(ALPHABET.replace("\n", " ").replace("\x00", "")) for _ in range(rng.randint(1, 200))) for _ in range(300)]
    res = run(chat_of(bodies, "Rahul") + chat_of(bodies[:50], "Sales - Neha"))
    assert "tasks" in res and 0 <= res["health"]["score"] <= 100


def test_header_lookalikes_inside_messages_are_not_split_incorrectly():
    text = "01/10/2026, 10:00 - Amit: see log\n02/10/2026, 11:11 - this line looks like a header but has no sender\nplain continuation\n"
    msgs = WhatsAppParser().parse_text(text)
    assert [m.is_system for m in msgs] == [False, True]
    assert msgs[1].raw_text.endswith("plain continuation")


@pytest.mark.parametrize("payload", [
    "a" * 200_000,
    " " * 200_000,
    "kal " * 50_000,
    "client " * 40_000 + "nahi",
    ("done " * 30_000) + "not",
    "instead of " * 20_000,
    "waiting for client " * 10_000,
    "(" * 5_000 + "x" + ")" * 5_000,
    "1/2/3/4/5/6/7/8/9/ " * 10_000,
], ids=["long-word", "spaces", "kal-repeat", "client-nahi", "done-not", "instead-of", "waiting-client", "parens", "date-like"])
def test_no_catastrophic_regex_backtracking(payload):
    t0 = time.perf_counter()
    signals(payload)
    extract_deadline(payload, __import__("datetime").datetime(2026, 10, 1))
    res = run(chat_of(["Amit please do " + payload, payload], "Rahul"))
    assert res["tasks"] is not None
    assert time.perf_counter() - t0 < 10, "pathological input took too long (possible ReDoS)"


def test_extreme_shapes():
    assert run(chat_of(["x"] * 5000)) is not None                     # many identical messages
    assert run("\n".join(f"01/10/2026, 10:00 - P{i}: hi" for i in range(2000)) + "\n") is not None   # 2000 senders
    one = chat_of(["Amit please build login by Friday " * 3])         # single-message chat
    assert len(run(one)["tasks"]) <= 1
    crlf = chat_of(["hello", "world"]).replace("\n", "\r\n")
    assert [m.text for m in WhatsAppParser().parse_text(crlf)] == ["hello", "world"]


def test_deterministic_ids_and_results():
    text = chat_of(["Amit please integrate Razorpay by Friday", "Working on payment", "Razorpay API integrated"], "Rahul")
    a, b = run(text), run(text)
    assert [t["id"] for t in a["tasks"]] == [t["id"] for t in b["tasks"]]
    assert a["progress"]["overall"] == b["progress"]["overall"]
