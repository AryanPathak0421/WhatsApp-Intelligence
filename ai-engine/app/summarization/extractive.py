"""Extractive chat summarisation: TextRank centrality + work-signal bonus + MMR diversity.

Selects ORIGINAL messages (never rewrites them), so every summary line is quoted evidence
with sender, time and message id. Works with any Embedder (hashing fallback or e5/MiniLM).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import numpy as np

from app.embeddings.embedder import Embedder, HashingEmbedder
from app.intelligence.rules import signals

WORK = ("done", "progress", "blocked", "client_wait", "approval", "reject", "bug", "bug_fixed", "decision", "meeting",
        "req_change", "assign", "commit", "payment", "deploy", "test_pass", "risk", "requirement")
CHATTER_MAX = 12  # chars: "ok", "thanks!", "👍"


def informative(m) -> float:
    """0..1 prior that a message carries project information (rules only, no model)."""
    if not m.sender or not m.text or len(m.text.strip()) <= CHATTER_MAX:
        return 0.0
    s = signals(m.text)
    hits = sum(s[k] for k in WORK)
    return min(1.0, 0.25 + 0.25 * hits) if hits else (0.2 if len(m.text) > 60 else 0.05)


def textrank(sim: np.ndarray, damping: float = 0.85, iters: int = 40) -> np.ndarray:
    n = len(sim)
    if n == 0:
        return np.zeros(0)
    w = np.clip(sim, 0, None)
    np.fill_diagonal(w, 0)
    rs = w.sum(1, keepdims=True)
    P = np.divide(w, rs, out=np.full_like(w, 1.0 / n), where=rs > 0)
    r = np.full(n, 1.0 / n)
    for _ in range(iters):
        r = (1 - damping) / n + damping * P.T @ r
    return r / r.max() if r.max() > 0 else r


def summarize_messages(msgs, k: int = 5, embedder: Optional[Embedder] = None, lam: float = 0.6, dup_sim: float = 0.85, max_pool: int = 600,
                       date_from: Optional[datetime] = None, date_to: Optional[datetime] = None) -> list[dict]:
    emb = embedder or HashingEmbedder()
    pool = [m for m in msgs if (date_from is None or m.ts >= date_from) and (date_to is None or m.ts <= date_to)
            and informative(m) > 0.1]
    if not pool:
        return []
    if len(pool) > max_pool:   # similarity matrix is O(n^2): keep the most informative candidates (ties -> most recent)
        keep = sorted(range(len(pool)), key=lambda i: (informative(pool[i]), pool[i].ts), reverse=True)[:max_pool]
        pool = [pool[i] for i in sorted(keep)]
    V = emb.encode([m.text for m in pool], "passage")
    sim = V @ V.T
    cent = textrank(sim)
    prior = np.array([informative(m) for m in pool])
    base = 0.5 * prior + 0.5 * cent * (prior > 0.1)
    chosen: list[int] = []
    while len(chosen) < min(k, len(pool)):
        best, best_s = None, -1e9
        for i in range(len(pool)):
            if i in chosen:
                continue
            red = max((sim[i, j] for j in chosen), default=0.0)
            if red >= dup_sim:  # near-duplicate of something already selected
                continue
            s = lam * base[i] - (1 - lam) * red  # MMR: relevance minus redundancy
            if s > best_s:
                best, best_s = i, s
        if best is None:
            break
        chosen.append(best)
    chosen.sort(key=lambda i: pool[i].ts)
    return [{"message_id": pool[i].id, "sender": pool[i].sender, "ts": pool[i].ts, "text": pool[i].text,
             "score": round(float(base[i]), 3)} for i in chosen]
