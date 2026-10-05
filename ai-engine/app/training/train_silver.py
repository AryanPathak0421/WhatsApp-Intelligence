"""Train the classifier on synthetic data + ONE real chat labelled by a model (reviewer "claude" = SILVER labels).

    python -m app.training.train_silver --chat ../private-data/anon/hg_enterprises.anon.txt \
        --annotations ../private-data/annotations/annotations.jsonl --reviewer claude --project hg-enterprises

Honesty rules (why this is NOT train_baseline's REAL_TEST):
  * the real labels are model-made and come from a single project, so no project-level hold-out exists;
  * evaluation is blocked K-fold over the chat (contiguous blocks, previous-message context stays inside the block's own chat order);
    every fold is scored by a model that never saw that block, but synthetic data and neighbouring blocks were seen;
  * the number is reported as SILVER_CV and is compared with the rule engine's own proposals on the same rows;
  * the repeat factor of the real rows is reported for every setting, not only the best one (picking the best on the same folds is optimistic).
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from app.annotation.prelabel import build_batch
from app.classifiers.baseline import MessageClassifier
from app.evaluation.metrics import evaluate
from app.labels import CATEGORIES, canonical
from app.training.train_baseline import XY, add_context, fit, load


def real_rows(chat: str, annotations: str, reviewer: str, project: str) -> list[dict]:
    """Chat-ordered rows {message, category, rules, _prev} for the messages this reviewer labelled."""
    items = sorted(build_batch(Path(chat).read_text(encoding="utf-8"), project, {})["items"], key=lambda i: i["index"])
    gold = {}
    for line in Path(annotations).open(encoding="utf-8"):
        if line.strip():
            r = json.loads(line)
            if r["reviewer"] == reviewer and r["project_id"] == project:
                gold[r["message_id"]] = canonical(r["category"])
    rows = [{"project_id": project, "message": i["message"], "category": gold[i["message_id"]],
             "rules": canonical(i["proposal"]["category"]), "rules_conf": i["proposal"]["confidence"]} for i in items if i["message_id"] in gold]
    return add_context(rows)


def blocks(n: int, k: int) -> list[range]:
    size = -(-n // k)
    return [range(i, min(i + size, n)) for i in range(0, n, size)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chat", required=True)
    ap.add_argument("--annotations", required=True)
    ap.add_argument("--reviewer", default="claude")
    ap.add_argument("--project", required=True)
    ap.add_argument("--synthetic", default="data/synthetic/gold.jsonl")
    ap.add_argument("--out", default="models/classifier")
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--repeat", type=int, default=5, help="repeat factor of real rows in the FINAL model")
    ap.add_argument("--save", action="store_true")
    a = ap.parse_args()

    syn = load(a.synthetic)
    for r in syn:
        r["project_id"] = "S:" + r["project_id"]
        r["category"] = canonical(r["category"])
    add_context(syn)
    real = real_rows(a.chat, a.annotations, a.reviewer, a.project)
    n = len(real)
    print(f"synthetic={len(syn)} real(silver)={n}")

    configs = [("lr", 20.0, False, 0), ("lr", 20.0, False, 5), ("lr", 20.0, False, 10), ("lr", 20.0, False, 20), ("lr", 20.0, True, 5)]
    folds = blocks(n, a.folds)
    out = {"rules_only": {"y": [], "p": []}}
    for cfg in configs:
        out[cfg] = {"y": [], "p": []}
    out["HYBRID rules, classifier(rep=10) when rules conf<=0.5"] = {"y": [], "p": []}
    for f in folds:
        test = [real[i] for i in f]
        train_real = [r for i, r in enumerate(real) if i not in f]
        out["rules_only"]["y"] += [r["category"] for r in test]
        out["rules_only"]["p"] += [r["rules"] for r in test]
        for cfg in configs:
            kind, C, ctx, rep = cfg
            pipe = fit(kind, C, ctx, syn + train_real * rep)
            X, y = XY(test, ctx)
            out[cfg]["y"] += y
            pred = list(pipe.predict(X))
            out[cfg]["p"] += pred
            if cfg[3] == 10:
                out["HYBRID rules, classifier(rep=10) when rules conf<=0.5"]["y"] += y
                out["HYBRID rules, classifier(rep=10) when rules conf<=0.5"]["p"] += [r["rules"] if r["rules_conf"] > 0.5 else c for r, c in zip(test, pred)]

    report = {}
    print(f"\nSILVER_CV ({a.folds} contiguous blocks over the chat, n={n}; reference = model-made labels)")
    for key, d in out.items():
        m = evaluate(d["y"], d["p"], CATEGORIES)
        name = key if isinstance(key, str) else f"classifier lr C={key[1]:g} ctx={key[2]} real_repeat={key[3]}"
        report[name] = {"n": m["n"], "accuracy": round(m["accuracy"], 3), "macro_f1": round(m["macro_f1"], 3)}
        print(f"  {name:48s} acc={m['accuracy']:.3f}  macroF1={m['macro_f1']:.3f}")

    if a.save:
        final = fit("lr", 20.0, True, syn + real * a.repeat)
        version = f"classifier_silver_{datetime.now(timezone.utc):%Y%m%d%H%M}"
        outd = Path(a.out)
        outd.mkdir(parents=True, exist_ok=True)
        MessageClassifier(final, version, True).save(outd / f"{version}.joblib")
        (outd / f"{version}.metrics.json").write_text(json.dumps({
            "version": version, "created_at": datetime.now(timezone.utc).isoformat(), "SILVER_CV": report,
            "note": "real labels are model-made (reviewer %s), single project; not a REAL_TEST" % a.reviewer,
            "dataset": {"synthetic_msgs": len(syn), "silver_msgs": n, "real_repeat": a.repeat}}, indent=2), encoding="utf-8")
        print("saved", outd / f"{version}.joblib")


if __name__ == "__main__":
    main()
