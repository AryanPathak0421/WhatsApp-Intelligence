"""Local transformer message classifier (inference). Fully offline once weights are on disk."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from app.classifiers.baseline import preprocess


def device() -> str:
    return "cuda" if torch.cuda.is_available() else "cpu"


def prefix_for(model_name: str) -> str:
    return "query: " if "e5" in model_name.lower() else ""


def encode_inputs(tok, texts, prevs, prefix, max_len, use_context):
    a = [prefix + preprocess(t) for t in texts]
    if use_context:
        b = [preprocess(p) if p else "" for p in prevs]
        return tok(a, b, truncation="longest_first", max_length=max_len, padding=True, return_tensors="pt")
    return tok(a, truncation=True, max_length=max_len, padding=True, return_tensors="pt")


class TransformerClassifier:
    def __init__(self, path: str | Path, version: str | None = None):
        path = Path(path)
        meta = json.loads((path / "wa_meta.json").read_text(encoding="utf-8"))
        self.labels: list[str] = meta["labels"]
        self.base_model, self.max_len = meta["base_model"], meta["max_len"]
        self.use_context = meta["use_context"]
        self.version = version or meta["version"]
        self.tok = AutoTokenizer.from_pretrained(path)
        self.model = AutoModelForSequenceClassification.from_pretrained(path).to(device()).eval()

    @torch.inference_mode()
    def predict(self, texts: list[str], prev_texts: list[str | None] | None = None,
                batch_size: int = 64) -> list[dict]:
        prev_texts = prev_texts or [None] * len(texts)
        out = []
        for i in range(0, len(texts), batch_size):
            enc = encode_inputs(self.tok, texts[i:i + batch_size], prev_texts[i:i + batch_size],
                                prefix_for(self.base_model), self.max_len, self.use_context)
            enc = {k: v.to(self.model.device) for k, v in enc.items()}
            proba = torch.softmax(self.model(**enc).logits, dim=-1).cpu().numpy()
            for row in proba:
                order = np.argsort(row)[::-1]
                out.append({"category": self.labels[order[0]], "confidence": float(row[order[0]]),
                            "margin": float(row[order[0]] - row[order[1]]),
                            "alternatives": [{"category": self.labels[j], "confidence": float(row[j])}
                                             for j in order[1:3]],
                            "model_version": self.version})
        return out
