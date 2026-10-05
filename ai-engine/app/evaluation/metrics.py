"""Classification metrics. Primary metric: macro-F1 (class imbalance)."""
from __future__ import annotations

from sklearn.metrics import (accuracy_score, confusion_matrix, f1_score,
                             precision_recall_fscore_support)


def evaluate(y_true: list[str], y_pred: list[str], labels: list[str]) -> dict:
    p, r, f, s = precision_recall_fscore_support(y_true, y_pred, labels=labels, zero_division=0)
    return {
        "n": len(y_true),
        "accuracy": accuracy_score(y_true, y_pred),
        "macro_f1": f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0),
        "weighted_f1": f1_score(y_true, y_pred, labels=labels, average="weighted", zero_division=0),
        "per_class": {l: {"precision": float(p[i]), "recall": float(r[i]), "f1": float(f[i]),
                          "support": int(s[i])} for i, l in enumerate(labels)},
        "labels": labels,
        "confusion_matrix": confusion_matrix(y_true, y_pred, labels=labels).tolist(),
    }


def calibration_table(conf: list[float], correct: list[bool],
                      bins=(0.0, 0.5, 0.7, 0.85, 0.95, 1.01)) -> list[dict]:
    """Does 'confidence' mean anything? Accuracy per confidence bucket."""
    out = []
    for lo, hi in zip(bins, bins[1:]):
        idx = [i for i, c in enumerate(conf) if lo <= c < hi]
        out.append({"range": f"{lo:.2f}-{min(hi, 1.0):.2f}", "n": len(idx),
                    "accuracy": (sum(correct[i] for i in idx) / len(idx)) if idx else None})
    return out
