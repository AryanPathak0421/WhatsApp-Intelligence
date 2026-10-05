"""Minimal ROUGE-1/2/L (F1) for summary evaluation against human reference summaries.

Needed once real (chat -> manager-written summary) pairs exist; until then summaries are validated
structurally by `verify_summary` (every number and id must match the analysis result).
"""
from __future__ import annotations

import re
from collections import Counter


def _tok(s: str) -> list[str]:
    return re.findall(r"\w+", s.lower())


def _f1(overlap: int, p_total: int, r_total: int) -> float:
    if not overlap or not p_total or not r_total:
        return 0.0
    p, r = overlap / p_total, overlap / r_total
    return 2 * p * r / (p + r)


def _ngrams(t, n):
    return Counter(tuple(t[i:i + n]) for i in range(len(t) - n + 1))


def _lcs(a, b) -> int:
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b, 1):
            cur.append(prev[j - 1] + 1 if x == y else max(prev[j], cur[-1]))
        prev = cur
    return prev[-1]


def rouge(candidate: str, reference: str) -> dict:
    c, r = _tok(candidate), _tok(reference)
    out = {}
    for n in (1, 2):
        cn, rn = _ngrams(c, n), _ngrams(r, n)
        out[f"rouge{n}"] = round(_f1(sum((cn & rn).values()), sum(cn.values()), sum(rn.values())), 4)
    out["rougeL"] = round(_f1(_lcs(c, r), len(c), len(r)), 4)
    return out
