"""Document store with hybrid retrieval: BM25 + dense vectors + metadata filters -> reciprocal-rank fusion -> rerank -> parent expansion.

Scope = access control. "global" documents (the shared paper library) are visible to every signed-in user; a project's documents are visible only
when the caller has proven access to that project (the API layer checks it with the backend before passing the scope in `allowed_scopes`).
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Optional

import numpy as np

from .ingest import Chunk, Doc
from .rerank import LexicalReranker, Reranker, terms


class HashingEmbedder:
    """Dependency-free lexical embedding (tests, small corpora). Swap in a multilingual-e5 / BGE encoder with the same .encode() for real use."""
    def __init__(self, dim: int = 384):
        self.dim, self.name = dim, f"hashing-{dim}"

    def encode(self, texts: list[str], kind: str = "passage") -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            ws = terms(t)
            for f in ws + [a + " " + b for a, b in zip(ws, ws[1:])]:
                h = int(hashlib.md5(f.encode()).hexdigest()[:8], 16)
                out[i, h % self.dim] += 1.0 if (h >> 31) & 1 else -1.0
        n = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.clip(n, 1e-9, None)


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.4, b: float = 0.75):
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


def rrf(rank_lists: list[list[int]], k: int = 60) -> dict[int, float]:
    out: dict[int, float] = defaultdict(float)
    for ranks in rank_lists:
        for r, i in enumerate(ranks):
            out[i] += 1.0 / (k + r + 1)
    return out


class DocumentStore:
    def __init__(self, directory: Optional[str | Path] = None, embedder=None, reranker: Optional[Reranker] = None):
        self.dir = Path(directory) if directory else None
        self.emb = embedder or HashingEmbedder()
        self.reranker = reranker or LexicalReranker()
        self.docs: dict[str, Doc] = {}
        self.chunks: list[Chunk] = []
        self._vec: Optional[np.ndarray] = None
        self._bm25: Optional[BM25] = None
        if self.dir:
            self.dir.mkdir(parents=True, exist_ok=True)
            self._load()

    # ---- persistence ----
    def _load(self):
        for p in sorted(self.dir.glob("d_*.json")):
            j = json.loads(p.read_text(encoding="utf-8"))
            self.docs[j["doc"]["id"]] = Doc(**j["doc"])
            self.chunks += [Chunk(**c) for c in j["chunks"]]

    def add(self, doc: Doc, chunks: list[Chunk]) -> bool:
        """Idempotent by content hash. Returns False if the same file was already ingested."""
        if doc.id in self.docs:
            return False
        self.docs[doc.id] = doc
        self.chunks += chunks
        self._vec = self._bm25 = None
        if self.dir:
            (self.dir / f"{doc.id}.json").write_text(json.dumps({"doc": doc.__dict__, "chunks": [c.__dict__ for c in chunks]}, ensure_ascii=False), encoding="utf-8")
        return True

    def remove(self, doc_id: str) -> bool:
        if doc_id not in self.docs:
            return False
        del self.docs[doc_id]
        self.chunks = [c for c in self.chunks if c.doc_id != doc_id]
        self._vec = self._bm25 = None
        if self.dir and (self.dir / f"{doc_id}.json").exists():
            (self.dir / f"{doc_id}.json").unlink()
        return True

    def _index(self):
        if self._bm25 is None:
            self._bm25 = BM25([terms(c.text + " " + c.section) for c in self.chunks])
            self._vec = self.emb.encode([c.text for c in self.chunks]) if self.chunks else np.zeros((0, self.emb.dim), np.float32)

    # ---- search ----
    def search(self, query: str, allowed_scopes: Iterable[str] = ("global",), *, k: int = 5, year_min: Optional[int] = None,
               tag: Optional[str] = None, doc_id: Optional[str] = None, candidates: int = 40) -> list[dict]:
        if not self.chunks or not query.strip():
            return []
        self._index()
        scopes = set(allowed_scopes)
        ok = np.array([self.docs[c.doc_id].scope in scopes
                       and (year_min is None or (self.docs[c.doc_id].year or 0) >= year_min)
                       and (tag is None or tag.lower() in [t.lower() for t in self.docs[c.doc_id].tags])
                       and (doc_id is None or c.doc_id == doc_id) for c in self.chunks])
        if not ok.any():
            return []
        bm = np.where(ok, self._bm25.scores(terms(query)), -1.0)
        dn = np.where(ok, self._vec @ self.emb.encode([query], "query")[0], -1.0)
        lists = []
        for s in (bm, dn):
            order = [int(i) for i in np.argsort(-s) if ok[i]][:candidates]
            lists.append([i for i in order if s[i] > 0] or order[:0])
        fused = rrf(lists)
        top = sorted(fused, key=fused.get, reverse=True)[:candidates]
        if not top:
            return []
        rr = self.reranker.score(query, [self.chunks[i].text for i in top])
        ranked = sorted(zip(top, rr), key=lambda x: (-x[1], -fused[x[0]]))[:k]
        out = []
        for n, (i, score) in enumerate(ranked, 1):
            c, d = self.chunks[i], self.docs[self.chunks[i].doc_id]
            out.append({"citation": f"C{n}", "chunk_id": c.id, "doc_id": d.id, "title": d.title, "authors": d.authors, "year": d.year, "doi": d.doi,
                        "source_url": d.source_url, "page": c.page, "section": c.section, "text": c.text, "context": c.parent_text[:1200],
                        "relevance": round(float(score), 3), "scope": d.scope})
        return out
