"""Inter-annotator agreement (Cohen's kappa) on the category label.

    python -m app.evaluation.agreement annotatorA.jsonl annotatorB.jsonl

Both files are annotation exports (one JSON object per line with project_id, message_id, category). Only messages labelled by BOTH are compared.
Rule of thumb: kappa >= 0.7 is acceptable for training data, 0.6-0.7 means the guidelines need work, < 0.6 means do not train on it yet.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from app.labels import canonical


def load(path) -> dict[tuple, str]:
    out = {}
    for line in Path(path).open(encoding="utf-8"):
        if line.strip():
            r = json.loads(line)
            out[(r["project_id"], r["message_id"])] = canonical(r["category"])   # later lines win, like the annotation store
    return out


def cohen_kappa(a: list[str], b: list[str]) -> float:
    n = len(a)
    if n == 0:
        raise ValueError("no overlapping annotations")
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def compare(a: dict, b: dict) -> dict:
    keys = sorted(set(a) & set(b))
    la, lb = [a[k] for k in keys], [b[k] for k in keys]
    k = cohen_kappa(la, lb)
    confusions = Counter((x, y) for x, y in zip(la, lb) if x != y).most_common(8)
    return {"n_overlap": len(keys), "agreement": sum(x == y for x, y in zip(la, lb)) / len(keys), "kappa": k,
            "verdict": "OK for training" if k >= 0.7 else "refine the guidelines" if k >= 0.6 else "do not train on this yet",
            "top_disagreements": [{"a": x, "b": y, "count": c} for (x, y), c in confusions]}


if __name__ == "__main__":
    print(json.dumps(compare(load(sys.argv[1]), load(sys.argv[2])), indent=2))
