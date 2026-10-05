"""Baseline message classifier: word + char TF-IDF -> linear model.

Char n-grams matter: Hinglish spellings vary ("kr diya"/"kar diya"/"kardiya").
Class imbalance handled with class_weight="balanced".
Context option appends the previous message so "Done" after "Payment API?" is learnable.
"""
from __future__ import annotations

import re
import unicodedata

import joblib
import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.svm import LinearSVC

_URL = re.compile(r"https?://\S+")
_NUM = re.compile(r"\d+")


def preprocess(text: str) -> str:
    """Light normalisation for MODEL INPUT only (original text is never changed)."""
    t = unicodedata.normalize("NFKC", text).lower()
    t = _URL.sub(" URL ", t)
    t = _NUM.sub("0", t)
    return t.strip()


def with_context(text: str, prev: str | None) -> str:
    return f"{preprocess(text)} ||| {preprocess(prev)}" if prev else preprocess(text)


def _features():
    return FeatureUnion([
        ("word", TfidfVectorizer(analyzer="word", ngram_range=(1, 2), sublinear_tf=True,
                                 token_pattern=r"(?u)\b\w+\b")),
        ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), min_df=2, sublinear_tf=True)),
    ])


def build(kind: str = "lr", C: float = 10.0) -> Pipeline:
    if kind == "lr":
        clf = LogisticRegression(C=C, max_iter=2000, class_weight="balanced")
    elif kind == "svm":  # calibrated so predict_proba exists (confidence)
        clf = CalibratedClassifierCV(LinearSVC(C=C / 10, class_weight="balanced"), cv=3)
    else:
        raise ValueError(kind)
    return Pipeline([("feat", _features()), ("clf", clf)])


class MessageClassifier:
    def __init__(self, pipeline: Pipeline, version: str, use_context: bool = False):
        self.pipeline, self.version, self.use_context = pipeline, version, use_context

    @property
    def labels(self) -> list[str]:
        return list(self.pipeline.classes_)

    def predict(self, texts: list[str], prev_texts: list[str | None] | None = None) -> list[dict]:
        prev_texts = prev_texts or [None] * len(texts)
        X = [with_context(t, p if self.use_context else None) for t, p in zip(texts, prev_texts)]
        proba = self.pipeline.predict_proba(X)
        out = []
        for row in proba:
            order = np.argsort(row)[::-1]
            top, second = order[0], order[1]
            out.append({"category": self.labels[top], "confidence": float(row[top]),
                        "margin": float(row[top] - row[second]),
                        "alternatives": [{"category": self.labels[j], "confidence": float(row[j])}
                                         for j in order[1:3]],
                        "model_version": self.version})
        return out

    def save(self, path):
        joblib.dump({"pipeline": self.pipeline, "version": self.version,
                     "use_context": self.use_context}, path)

    @classmethod
    def load(cls, path):
        d = joblib.load(path)
        return cls(d["pipeline"], d["version"], d["use_context"])
