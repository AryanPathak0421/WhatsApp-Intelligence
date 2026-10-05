"""Benchmark local embedders on the handwritten probe (eval/embedding_probe.json).

    python -m app.evaluation.embedding_benchmark [model ...]

The probe is small (42 messages, 15 queries, 36 task/message pairs), written by the developer:
use it to compare candidates and pick a threshold, not as proof of production accuracy.
"""
from __future__ import annotations

import json
import sys
import time

import numpy as np

from app.embeddings.embedder import HashingEmbedder, HFEmbedder

DEFAULT = ["hashing", "intfloat/multilingual-e5-small",
           "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", "BAAI/bge-small-en-v1.5"]


def auc(pos, neg):
    return float(np.mean([(p > n) + 0.5 * (p == n) for p in pos for n in neg]))


def best_threshold(sims, labels):
    best = (0, 0.0)
    for t in sorted(set(sims)):
        acc = np.mean([(s >= t) == bool(l) for s, l in zip(sims, labels)])
        if acc > best[0]:
            best = (float(acc), float(t))
    return best


def evaluate(emb, probe):
    corpus = probe["corpus"]
    t0 = time.perf_counter()
    C = emb.encode(corpus, "passage")
    lat = (time.perf_counter() - t0) / len(corpus) * 1000
    rec3 = mrr = p3 = 0.0
    for q in probe["queries"]:
        s = C @ emb.encode([q["q"]], "query")[0]
        order = np.argsort(-s)
        rel = set(q["relevant"])
        top3 = order[:3]
        rec3 += len(rel & set(top3)) / min(3, len(rel))
        p3 += len(rel & set(top3)) / 3
        mrr += next((1 / (r + 1) for r, i in enumerate(order) if i in rel), 0.0)
    n = len(probe["queries"])
    A = emb.encode([p["task"] for p in probe["pairs"]], "passage")
    B = emb.encode([p["message"] for p in probe["pairs"]], "passage")
    sims = [float(a @ b) for a, b in zip(A, B)]
    lab = [p["same"] for p in probe["pairs"]]
    acc, thr = best_threshold(sims, lab)
    pos = [s for s, l in zip(sims, lab) if l]
    neg = [s for s, l in zip(sims, lab) if not l]
    return {"recall@3": round(rec3 / n, 3), "precision@3": round(p3 / n, 3), "MRR": round(mrr / n, 3),
            "pair_AUC": round(auc(pos, neg), 3), "pair_best_acc": round(acc, 3), "pair_threshold": round(thr, 3),
            "pos_mean": round(float(np.mean(pos)), 3), "neg_mean": round(float(np.mean(neg)), 3),
            "neg_p95": round(float(np.percentile(neg, 95)), 3), "pos_p05": round(float(np.percentile(pos, 5)), 3),
            "ms_per_msg": round(lat, 1), "dim": emb.dim}


def main():
    probe = json.load(open("eval/embedding_probe.json", encoding="utf-8"))
    names = sys.argv[1:] or DEFAULT
    rows = {}
    for n in names:
        try:
            emb = HashingEmbedder() if n == "hashing" else HFEmbedder(n)
            rows[n] = evaluate(emb, probe)
        except Exception as e:  # model unavailable offline etc.
            rows[n] = {"error": str(e)[:120]}
        print(n, json.dumps(rows[n]), flush=True)
    json.dump(rows, open("models/embedding_benchmark.json", "w"), indent=1)


if __name__ == "__main__":
    main()
