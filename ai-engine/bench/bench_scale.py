"""Scale benchmark: parse + full analysis on synthetic chats of N messages.

    python -m bench.bench_scale 10000 50000 100000
Reports wall time per stage and peak RSS. Synthetic data, so absolute numbers are indicative of CPU cost only.
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta

import psutil

from app.datasets.synthetic import _fmt, generate_project
from app.intelligence.pipeline import analyze
from app.intelligence.types import Msg
from app.parsers.whatsapp import WhatsAppParser


def make_chat(n_messages: int) -> str:
    """Concatenate synthetic projects, spaced 3 weeks apart so tasks do not merge across them."""
    lines, count, k = [], 0, 0
    while count < n_messages:
        chat, gold, style = generate_project(1000 + k, f"b{k}", n_tasks=10)
        base = datetime(2026, 1, 1) + timedelta(weeks=3 * k)
        t0 = datetime.fromisoformat(gold[0]["timestamp"])
        for g in gold:
            ts = base + (datetime.fromisoformat(g["timestamp"]) - t0)
            lines.append(_fmt(ts, g["sender"], g["message"], "android24"))
            count += 1
        k += 1
    return "\n".join(lines[:n_messages]) + "\n"


def rss() -> float:
    return psutil.Process().memory_info().rss / 1e6


def main(sizes):
    print(f"{'msgs':>8} {'parse s':>8} {'analyze s':>10} {'msgs/s':>8} {'tasks':>6} {'peak MB':>8}")
    for n in sizes:
        text = make_chat(n)
        t = time.perf_counter()
        parsed = WhatsAppParser().parse_text(text)
        t_parse = time.perf_counter() - t
        msgs = [Msg.from_parsed(m) for m in parsed]
        t = time.perf_counter()
        res = analyze(msgs)
        t_an = time.perf_counter() - t
        print(f"{len(msgs):>8} {t_parse:>8.1f} {t_an:>10.1f} {len(msgs) / (t_an + t_parse):>8.0f} {len(res['tasks']):>6} {rss():>8.0f}", flush=True)


if __name__ == "__main__":
    main([int(x) for x in sys.argv[1:]] or [2000, 10000])
