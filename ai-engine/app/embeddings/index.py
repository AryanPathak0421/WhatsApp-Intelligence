"""Per-project vector index (exact cosine, numpy). One index == one project (hard isolation).

Exact search is fine to ~1M x 384 float32 (~1.5 GB) in chunks. For production scale the same
vectors go into PostgreSQL pgvector (`MessageEmbedding.embedding vector(384)`, see schema.prisma);
this class is the offline / worker-side implementation and the reference for tests.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

import numpy as np


class VectorIndex:
    def __init__(self, project_id: str, dim: int, model: str):
        self.project_id, self.dim, self.model = project_id, dim, model
        self.ids: list[str] = []
        self.meta: list[dict] = []
        self._chunks: list[np.ndarray] = []
        self._mat: Optional[np.ndarray] = None

    def __len__(self):
        return len(self.ids)

    def add(self, ids: list[str], vectors: np.ndarray, meta: list[dict]):
        assert vectors.shape == (len(ids), self.dim) and len(meta) == len(ids)
        known = set(self.ids)
        keep = [i for i, x in enumerate(ids) if x not in known]  # idempotent (incremental import)
        if not keep:
            return 0
        self.ids += [ids[i] for i in keep]
        self.meta += [meta[i] for i in keep]
        self._chunks.append(vectors[keep].astype(np.float32))
        self._mat = None
        return len(keep)

    @property
    def matrix(self) -> np.ndarray:
        if self._mat is None:
            self._mat = np.concatenate(self._chunks) if self._chunks else np.zeros((0, self.dim), np.float32)
            self._chunks = [self._mat] if len(self._mat) else []
        return self._mat

    def search(self, qvec: np.ndarray, k: int = 10, flt: Optional[Callable[[dict], bool]] = None,
               chunk: int = 200_000) -> list[tuple[str, float, dict]]:
        q = qvec.reshape(-1).astype(np.float32)
        M = self.matrix
        if not len(M):
            return []
        sims = np.concatenate([M[i:i + chunk] @ q for i in range(0, len(M), chunk)])
        if flt is not None:
            mask = np.array([flt(m) for m in self.meta])
            sims = np.where(mask, sims, -np.inf)
        k = min(k, int(np.isfinite(sims).sum()))
        if k <= 0:
            return []
        top = np.argpartition(-sims, k - 1)[:k]
        top = top[np.argsort(-sims[top])]
        return [(self.ids[i], float(sims[i]), self.meta[i]) for i in top]

    def save(self, path: str | Path):
        import json
        np.savez_compressed(path, matrix=self.matrix, ids=np.array(self.ids, dtype=object),
                            meta=json.dumps(self.meta, default=str), project=self.project_id, dim=self.dim, model=self.model)

    @classmethod
    def load(cls, path: str | Path) -> "VectorIndex":
        import json
        d = np.load(path, allow_pickle=True)
        idx = cls(str(d["project"]), int(d["dim"]), str(d["model"]))
        idx.add(list(d["ids"]), d["matrix"], json.loads(str(d["meta"])))
        return idx
