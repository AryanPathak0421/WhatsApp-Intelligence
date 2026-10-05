"""Train + evaluate the baseline classifier with PROJECT-LEVEL splits.

    python -m app.training.train_baseline

Reporting rules (enforced here):
  * REAL_TEST comes ONLY from human-labelled real projects held out by project;
  * synthetic data is train/val only; its score is labelled SYNTHETIC_ONLY (optimistic);
  * the handwritten probe is a small out-of-template smoke check, not a benchmark;
  * model selection uses validation only; all reported numbers come from a model
    that never saw the evaluated rows.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from app.classifiers.baseline import MessageClassifier, build, with_context
from app.datasets.split import split_projects
from app.evaluation.metrics import calibration_table, evaluate
from app.labels import CATEGORIES


def load(path):
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.open(encoding="utf-8") if line.strip()]


def add_context(rows):
    """Attach previous-message text within the same project (rows are in chat order)."""
    prev = {}
    for r in rows:
        r["_prev"] = prev.get(r["project_id"])
        prev[r["project_id"]] = r["message"]
    return rows


def XY(rows, ctx):
    return ([with_context(r["message"], r["_prev"] if ctx else None) for r in rows],
            [r["category"] for r in rows])


def fit(kind, C, ctx, rows):
    pipe = build(kind, C)
    X, y = XY(rows, ctx)
    return pipe.fit(X, y)


def score(pipe, rows, ctx):
    X, y = XY(rows, ctx)
    pred = list(pipe.predict(X))
    proba = pipe.predict_proba(X)
    m = evaluate(y, pred, CATEGORIES)
    m["calibration"] = calibration_table([float(p.max()) for p in proba],
                                         [a == b for a, b in zip(y, pred)])
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic", default="data/synthetic/gold.jsonl")
    ap.add_argument("--annotations", default="data/annotated/annotations.jsonl")
    ap.add_argument("--probe", default="eval/probe_handwritten.jsonl")
    ap.add_argument("--out", default="models/classifier")
    a = ap.parse_args()

    syn = load(a.synthetic)
    for r in syn:
        r["project_id"] = "S:" + r["project_id"]
    add_context(syn)
    human = add_context([r for r in load(a.annotations) if r.get("source") == "human"])
    probe = add_context(load(a.probe))
    print(f"synthetic={len(syn)} human={len(human)} probe={len(probe)}")

    syn_split = split_projects([r["project_id"] for r in syn], val=0.25, allow_test=False)
    train = [r for r in syn if syn_split[r["project_id"]] == "train"]
    val = [r for r in syn if syn_split[r["project_id"]] == "val"]
    real_test = []
    if human:
        rs = split_projects([r["project_id"] for r in human], val=0.2, test=0.2)
        train += [r for r in human if rs[r["project_id"]] == "train"]
        val += [r for r in human if rs[r["project_id"]] == "val"]
        real_test = [r for r in human if rs[r["project_id"]] == "test"]
    pids = lambda rows: {r["project_id"] for r in rows}  # noqa: E731
    assert not pids(train) & (pids(val) | pids(real_test)), "project leakage"
    print(f"train={len(train)} val={len(val)} real_test={len(real_test)}")

    results = []
    for kind, C in [("lr", 5.0), ("lr", 20.0), ("svm", 10.0)]:
        for ctx in (False, True):
            m = score(fit(kind, C, ctx, train), val, ctx)
            results.append({"kind": kind, "C": C, "context": ctx, "val_macro_f1": m["macro_f1"]})
            print(f"  {kind:3} C={C:<5} ctx={ctx!s:5} val macroF1={m['macro_f1']:.3f}")
    best = max(results, key=lambda r: r["val_macro_f1"])
    print("selected:", best)

    ctx = best["context"]
    held = fit(best["kind"], best["C"], ctx, train)  # never saw val / probe / test
    report = {"selected": best, "candidates": results,
              "SYNTHETIC_ONLY_val": score(held, val, ctx),
              "handwritten_probe": score(held, probe, ctx) if probe else None,
              "REAL_TEST": score(held, real_test, ctx) if real_test else None}
    for k in ("SYNTHETIC_ONLY_val", "handwritten_probe", "REAL_TEST"):
        m = report[k]
        print(f"{k}: " + (f"n={m['n']} acc={m['accuracy']:.3f} macroF1={m['macro_f1']:.3f}" if m else "none"))
    if not real_test:
        print("REAL_TEST: none yet -> no honest accuracy claim possible. Annotate real chats.")

    final = fit(best["kind"], best["C"], ctx, train + val)
    version = f"classifier_baseline_{datetime.now(timezone.utc):%Y%m%d%H%M}"
    report.update(version=version, created_at=datetime.now(timezone.utc).isoformat(),
                  dataset={"synthetic_msgs": len(syn), "human_msgs": len(human),
                           "hash": hashlib.sha256("\n".join(r["message"] for r in train + val).encode()
                                                  ).hexdigest()[:12]})
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    MessageClassifier(final, version, ctx).save(out / f"{version}.joblib")
    (out / f"{version}.metrics.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("saved", out / f"{version}.joblib")


if __name__ == "__main__":
    main()
