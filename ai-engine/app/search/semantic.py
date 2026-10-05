"""Project-scoped hybrid search (semantic + BM25) with source-message context.

Every hit is an original chat message (id, sender, time) plus its surrounding messages, so any
answer built on search stays traceable to WhatsApp text.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import datetime
from typing import Optional

import numpy as np

from app.embeddings.embedder import Embedder
from app.embeddings.index import VectorIndex
from app.intelligence.topics import ALIASES, stem, tokens

_ALIAS_OF = {t: g for g, ts in ALIASES.items() for t in ts}


def _lex_tokens(text: str, expand: bool) -> list[str]:
    out = []
    for w in tokens(text):
        out.append(stem(w))
        if expand and w in _ALIAS_OF:
            out += [stem(x) for x in ALIASES[_ALIAS_OF[w]]]  # "payment" also matches razorpay / gateway
    return out


class BM25:
    def __init__(self, docs: list[list[str]], k1=1.4, b=0.75):
        self.k1, self.b = k1, b
        self.tf = [Counter(d) for d in docs]
        self.len = np.array([len(d) for d in docs], dtype=float)
        self.avg = float(self.len.mean()) if len(docs) else 1.0
        df = Counter(t for d in self.tf for t in d)
        n = len(docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        self.inv = defaultdict(list)
        for i, d in enumerate(self.tf):
            for t in d:
                self.inv[t].append(i)

    def scores(self, q: list[str]) -> np.ndarray:
        s = np.zeros(len(self.tf))
        for t in set(q):
            idf = self.idf.get(t)
            if idf is None:
                continue
            for i in self.inv[t]:
                f = self.tf[i][t]
                s[i] += idf * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.len[i] / self.avg))
        return s


class ProjectSearch:
    def __init__(self, project_id: str, embedder: Embedder):
        self.project_id, self.emb = project_id, embedder
        self.index = VectorIndex(project_id, embedder.dim, embedder.name)
        self.msgs: list[dict] = []
        self._pos: dict[str, int] = {}
        self._bm25: Optional[BM25] = None

    def add_messages(self, msgs) -> int:
        """msgs: objects with id, text, sender, ts, index (Msg). System / empty messages are skipped."""
        rows = [m for m in msgs if m.sender and m.text and len(m.text.strip()) > 1 and m.id not in self._pos]
        if not rows:
            return 0
        vecs = self.emb.encode([m.text for m in rows], "passage")
        for m in rows:
            self._pos[m.id] = len(self.msgs)
            self.msgs.append({"id": m.id, "sender": m.sender, "ts": m.ts, "text": m.text, "index": m.index})
        self.index.add([m.id for m in rows], vecs,
                       [{"project_id": self.project_id, "sender": m.sender, "ts": m.ts} for m in rows])
        self._bm25 = None
        return len(rows)

    def _lex(self) -> BM25:
        if self._bm25 is None:
            self._bm25 = BM25([_lex_tokens(m["text"], False) for m in self.msgs])
        return self._bm25

    def search(self, query: str, k: int = 8, mode: str = "hybrid", sender: Optional[str] = None,
               date_from: Optional[datetime] = None, date_to: Optional[datetime] = None,
               context: int = 2, rrf_k: int = 60) -> list[dict]:
        if not self.msgs:
            return []
        keep = np.array([(sender is None or m["sender"] == sender) and (date_from is None or m["ts"] >= date_from)
                         and (date_to is None or m["ts"] <= date_to) for m in self.msgs])
        if not keep.any():
            return []
        sem = self.index.matrix @ self.emb.encode([query], "query")[0]
        lex = self._lex().scores(_lex_tokens(query, True))
        sem = np.where(keep, sem, -np.inf)
        lex_f = np.where(keep & (lex > 0), lex, -np.inf)
        score = defaultdict(float)
        for name, arr in (("semantic", sem), ("lexical", lex_f)):
            if mode not in ("hybrid", name):
                continue
            order = np.argsort(-arr)[:max(k * 3, 20)]
            for r, i in enumerate(order):
                if np.isfinite(arr[i]):
                    score[i] += 1.0 / (rrf_k + r + 1)
        top = sorted(score, key=lambda i: -score[i])[:k]
        out = []
        for i in top:
            lo, hi = max(0, i - context), min(len(self.msgs), i + context + 1)
            out.append({"message_id": self.msgs[i]["id"], "score": round(score[i] * rrf_k, 3),
                        "semantic": round(float(sem[i]), 3) if np.isfinite(sem[i]) else None,
                        "lexical": round(float(lex[i]), 3), "sender": self.msgs[i]["sender"],
                        "ts": self.msgs[i]["ts"], "text": self.msgs[i]["text"],
                        "context": [{"message_id": m["id"], "sender": m["sender"], "text": m["text"], "ts": m["ts"]}
                                    for m in self.msgs[lo:hi] if m["id"] != self.msgs[i]["id"]]})
        return out
