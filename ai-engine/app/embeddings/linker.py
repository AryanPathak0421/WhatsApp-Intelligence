"""Semantic task linker: maps embedding cosine to a 0-1 'same topic' score for build_tasks().

Cosine ranges differ per model (multilingual-e5 is compressed around 0.85), so each model has a
(lo, hi) profile derived from eval/embedding_probe.json (negatives p95 -> positives mean).
PROVISIONAL: derived from 36 handwritten pairs; re-fit on real linked-task pairs when available.
"""
from __future__ import annotations

import numpy as np

from app.embeddings.embedder import Embedder

PROFILES = {
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2": (0.27, 0.55),
    "BAAI/bge-small-en-v1.5": (0.61, 0.70),
    "intfloat/multilingual-e5-small": (0.88, 0.92),
    "hashing-384": (0.09, 0.20),
}


class SemanticLinker:
    def __init__(self, embedder: Embedder, lo: float | None = None, hi: float | None = None):
        self.emb = embedder
        d_lo, d_hi = PROFILES.get(embedder.name, (0.5, 0.8))
        self.lo, self.hi = lo if lo is not None else d_lo, hi if hi is not None else d_hi
        self._msg: dict[str, np.ndarray] = {}
        self._task: dict[str, np.ndarray] = {}

    def prepare(self, msgs) -> None:
        rows = [m for m in msgs if m.sender and m.text and len(m.text) > 3 and m.id not in self._msg]
        if rows:
            for m, v in zip(rows, self.emb.encode([m.text for m in rows], "passage")):
                self._msg[m.id] = v

    def sim(self, message_id: str, task_title: str) -> float:
        v = self._msg.get(message_id)
        if v is None or not task_title:
            return 0.0
        t = self._task.get(task_title)
        if t is None:
            t = self._task[task_title] = self.emb.encode([task_title], "passage")[0]
        return float(np.clip((float(v @ t) - self.lo) / (self.hi - self.lo), 0.0, 1.0))
