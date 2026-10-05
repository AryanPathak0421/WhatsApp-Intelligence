"""Local text embedders. No network calls at inference (weights are loaded from disk / HF cache).

* HFEmbedder      - any BERT-style encoder with mean pooling (multilingual-e5, paraphrase-multilingual-MiniLM, bge ...)
* HashingEmbedder - dependency-free char/word n-gram hashing fallback (used in tests and as a lexical baseline)
"""
from __future__ import annotations

import hashlib
import re
from typing import Protocol

import numpy as np

from app.classifiers.baseline import preprocess


class Embedder(Protocol):
    name: str
    dim: int

    def encode(self, texts: list[str], kind: str = "passage") -> np.ndarray: ...


def _norm(x: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(x, axis=1, keepdims=True)
    return x / np.clip(n, 1e-9, None)


class HashingEmbedder:
    def __init__(self, dim: int = 384):
        self.dim, self.name = dim, f"hashing-{dim}"

    def encode(self, texts, kind="passage"):
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            t = preprocess(t)
            feats = re.findall(r"\w+", t) + [t[j:j + 4] for j in range(max(0, len(t) - 3))]
            for f in feats:
                h = int(hashlib.md5(f.encode()).hexdigest()[:8], 16)
                out[i, h % self.dim] += 1.0 if (h >> 31) & 1 else -1.0
        return _norm(out)


class HFEmbedder:
    def __init__(self, model_name: str = "intfloat/multilingual-e5-small", max_len: int = 64,
                 batch_size: int = 64, device: str | None = None):
        import torch
        from transformers import AutoModel, AutoTokenizer
        self.torch = torch
        self.name = model_name
        self.max_len, self.batch_size = max_len, batch_size
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.tok = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModel.from_pretrained(model_name).to(self.device).eval()
        self.dim = self.model.config.hidden_size
        self._e5 = "e5" in model_name.lower()

    def _prep(self, t: str, kind: str) -> str:
        t = preprocess(t)
        return (f"{kind}: {t}" if self._e5 else t)

    def encode(self, texts, kind="passage"):
        torch = self.torch
        out = []
        with torch.inference_mode():
            for i in range(0, len(texts), self.batch_size):
                enc = self.tok([self._prep(t, kind) for t in texts[i:i + self.batch_size]], padding=True,
                               truncation=True, max_length=self.max_len, return_tensors="pt").to(self.device)
                h = self.model(**enc).last_hidden_state
                mask = enc["attention_mask"].unsqueeze(-1).to(h.dtype)
                out.append(((h * mask).sum(1) / mask.sum(1).clamp(min=1e-9)).cpu().numpy())
        return _norm(np.concatenate(out).astype(np.float32)) if out else np.zeros((0, self.dim), np.float32)
