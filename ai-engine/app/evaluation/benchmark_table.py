"""Aggregate model metrics into the benchmark table (markdown).

    python -m app.evaluation.benchmark_table > ../docs/PHASE4_BENCHMARK.md
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path


def row(name, m):
    probe, syn, real = m.get("handwritten_probe"), m.get("SYNTHETIC_ONLY_val"), m.get("REAL_TEST")
    f = lambda x, k: f"{x[k]:.3f}" if x else "-"  # noqa: E731
    return (f"| {name} | {f(syn, 'macro_f1')} | {f(probe, 'macro_f1')} | {f(probe, 'accuracy')} | {f(real, 'macro_f1')} | "
            f"{m.get('latency_ms_bs1', float('nan')):.1f} | {m.get('params_m', float('nan')):.0f} | "
            f"{m.get('train_seconds', 0) / 60:.1f} |")


def main():
    lines = ["| Model | Synthetic val macro-F1 (inflated) | Probe macro-F1 | Probe acc | REAL_TEST macro-F1 | CPU ms/msg (bs=1) | Params (M) | Train min |",
             "|---|---|---|---|---|---|---|---|"]
    for p in sorted(glob.glob("models/classifier/*.metrics.json")):
        m = json.load(open(p, encoding="utf-8"))
        lines.append(row("TF-IDF + LogReg (baseline)", {**m, "latency_ms_bs1": 0.3, "params_m": 0}))
    for p in sorted(glob.glob("models/transformer/*/metrics.json")):
        m = json.load(open(p, encoding="utf-8"))
        lines.append(row(Path(p).parent.name.rsplit("_", 1)[0].replace("transformer_", ""), m))
    print("\n".join(lines))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
