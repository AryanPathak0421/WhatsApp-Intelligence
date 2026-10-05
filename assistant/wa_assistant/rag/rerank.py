"""Rerankers. Output score is in [0, 1] and is what the abstention threshold is compared with.

LexicalReranker   dependency-free fallback: weighted coverage of the query's content terms + a phrase bonus. Honest limitation: it cannot
                  match paraphrases, so with it the assistant abstains more often than it should.
CrossEncoderReranker  a multilingual cross-encoder (BGE-reranker class) loaded from local weights. NOT exercised in tests here: no weights
                  are present on this machine, so its accuracy is unmeasured until the Phase-0 bake-off.
"""
from __future__ import annotations

import math
import re
from typing import Protocol

STOP = set("a an the of to in on for and or is are was were be been it its this that these those with as by at from what which who whom how why "
           "does do did can could should would about into than then there their they them you your i we our not no yes please tell me say says said "
           "paper papers article study document documents".split())


def terms(text: str) -> list[str]:
    out = []
    for w in re.findall(r"\w+", text.lower()):
        if w in STOP or len(w) < 2:
            continue
        for suf in ("ing", "ed", "es", "s"):
            if len(w) > len(suf) + 3 and w.endswith(suf):
                w = w[: -len(suf)]
                break
        out.append(w)
    return out


class Reranker(Protocol):
    name: str

    def score(self, query: str, passages: list[str]) -> list[float]: ...


class LexicalReranker:
    name = "lexical-coverage"

    def score(self, query: str, passages: list[str]) -> list[float]:
        q = terms(query)
        if not q:
            return [0.0] * len(passages)
        uq = list(dict.fromkeys(q))
        toks = [set(terms(p)) for p in passages]
        df = {t: sum(1 for ts in toks if t in ts) for t in uq}
        n = max(len(passages), 1)
        idf = {t: math.log(1 + (n + 1) / (df[t] + 0.5)) for t in uq}
        total = sum(idf.values()) or 1.0
        bigrams = [" ".join(q[i:i + 2]) for i in range(len(q) - 1)]
        out = []
        for p, ts in zip(passages, toks):
            cov = sum(idf[t] for t in uq if t in ts) / total
            low = " ".join(terms(p))
            bonus = 0.15 * (sum(1 for b in bigrams if b in low) / len(bigrams)) if bigrams else 0.0
            out.append(min(1.0, cov * 0.85 + bonus))
        return out


class CrossEncoderReranker:
    def __init__(self, model_path: str, max_len: int = 384, device: str | None = None):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        self.torch, self.name, self.max_len = torch, f"cross-encoder:{model_path}", max_len
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.tok = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_path, local_files_only=True).to(self.device).eval()

    def score(self, query: str, passages: list[str]) -> list[float]:
        out = []
        with self.torch.inference_mode():
            for i in range(0, len(passages), 16):
                enc = self.tok([query] * len(passages[i:i + 16]), passages[i:i + 16], padding=True, truncation=True, max_length=self.max_len,
                               return_tensors="pt").to(self.device)
                out += self.torch.sigmoid(self.model(**enc).logits.reshape(-1)).cpu().tolist()
        return out
