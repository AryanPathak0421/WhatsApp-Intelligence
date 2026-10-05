"""Model monitoring: privacy-preserving prediction log + drift checks.

The log never stores message text - only ids, label, confidence, language and model version.
`check_drift` compares a recent window against a baseline (e.g. the first weeks after a model was promoted, or the REAL_TEST distribution)
and returns flags; any flag means "review the model / consider retraining", never an automatic action.
"""
from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from typing import Iterable, Optional

LOW_CONF = 0.70   # same line as the active-learning "needs annotation" lane


class PredictionLogger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, project_id: str, message_id: str, label: str, confidence: float, model_version: str, language: Optional[str] = None) -> None:
        rec = {"project_id": project_id, "message_id": message_id, "label": label, "confidence": round(confidence, 4),
               "model_version": model_version, "language": language}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")

    @staticmethod
    def read(path: str | Path) -> list[dict]:
        p = Path(path)
        return [json.loads(line) for line in p.open(encoding="utf-8") if line.strip()] if p.exists() else []


def summarize(preds: Iterable[dict]) -> dict:
    preds = list(preds)
    n = len(preds)
    if not n:
        return {"n": 0}
    labels = Counter(p["label"] for p in preds)
    langs = Counter(p.get("language") or "unknown" for p in preds)
    conf = [p["confidence"] for p in preds]
    return {"n": n, "mean_confidence": sum(conf) / n, "low_confidence_share": sum(c < LOW_CONF for c in conf) / n,
            "label_dist": {k: v / n for k, v in labels.items()}, "language_dist": {k: v / n for k, v in langs.items()}}


def psi(expected: dict, actual: dict, eps: float = 1e-4) -> float:
    """Population Stability Index between two categorical distributions (>0.2 is a common 'significant shift' rule of thumb)."""
    keys = set(expected) | set(actual)
    return sum((actual.get(k, 0) + eps - (expected.get(k, 0) + eps)) * math.log((actual.get(k, 0) + eps) / (expected.get(k, 0) + eps)) for k in keys)


def check_drift(baseline: dict, current: dict, min_n: int = 200, correction_rate: Optional[float] = None) -> dict:
    """Return {"status": OK|INSUFFICIENT_DATA|DRIFT, "flags": [...], "metrics": {...}}."""
    if current.get("n", 0) < min_n or baseline.get("n", 0) < min_n:
        return {"status": "INSUFFICIENT_DATA", "flags": [], "metrics": {"current_n": current.get("n", 0), "baseline_n": baseline.get("n", 0)}}
    flags = []
    m = {"label_psi": psi(baseline["label_dist"], current["label_dist"]), "language_psi": psi(baseline["language_dist"], current["language_dist"]),
         "mean_confidence_drop": baseline["mean_confidence"] - current["mean_confidence"],
         "low_confidence_increase": current["low_confidence_share"] - baseline["low_confidence_share"]}
    if m["label_psi"] > 0.2:
        flags.append(f"class distribution shifted (PSI {m['label_psi']:.2f})")
    if m["language_psi"] > 0.2:
        flags.append(f"language mix shifted (PSI {m['language_psi']:.2f}) - e.g. more Hinglish than the model was trained on")
    if m["mean_confidence_drop"] > 0.10:
        flags.append(f"mean confidence fell by {m['mean_confidence_drop']:.2f}")
    if m["low_confidence_increase"] > 0.15:
        flags.append(f"{m['low_confidence_increase'] * 100:.0f} points more predictions are low-confidence")
    if correction_rate is not None:
        m["human_correction_rate"] = correction_rate
        if correction_rate > 0.30:
            flags.append(f"reviewers correct {correction_rate * 100:.0f}% of reviewed predictions")
    return {"status": "DRIFT" if flags else "OK", "flags": flags, "metrics": m}


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="python -m app.monitoring.drift <baseline.jsonl> <current.jsonl>")
    ap.add_argument("baseline"); ap.add_argument("current")
    a = ap.parse_args(argv)
    res = check_drift(summarize(PredictionLogger.read(a.baseline)), summarize(PredictionLogger.read(a.current)))
    print(json.dumps(res, indent=2))
    return 0 if res["status"] != "DRIFT" else 3


if __name__ == "__main__":
    raise SystemExit(main())
