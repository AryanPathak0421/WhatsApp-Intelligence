"""Fine-tune a local (multilingual) encoder for message classification.

    python -m app.training.finetune_transformer --model intfloat/multilingual-e5-small --epochs 4

Same data rules as the baseline: project-level splits, synthetic = train/val only,
REAL_TEST only from human-labelled held-out projects, model selection on validation only.
Weights are downloaded once from the Hugging Face hub (public model files only; no chat
data is sent anywhere) and then run fully offline.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
from transformers import (AutoModelForSequenceClassification, AutoTokenizer,
                          get_linear_schedule_with_warmup)

from app.classifiers.transformer import device, encode_inputs, prefix_for
from app.datasets.split import split_projects
from app.evaluation.metrics import calibration_table, evaluate
from app.labels import CATEGORIES
from app.training.train_baseline import add_context, load

L2I = {l: i for i, l in enumerate(CATEGORIES)}


def batches(rows, bs, shuffle, rng=None):
    idx = list(range(len(rows)))
    if shuffle:
        rng.shuffle(idx)
    for i in range(0, len(idx), bs):
        yield [rows[j] for j in idx[i:i + bs]]


def make_batch(tok, rows, prefix, max_len, ctx):
    enc = encode_inputs(tok, [r["message"] for r in rows], [r["_prev"] for r in rows], prefix, max_len, ctx)
    return enc, torch.tensor([L2I[r["category"]] for r in rows])


@torch.inference_mode()
def predict_proba(model, tok, rows, prefix, max_len, ctx, bs=64):
    model.eval()
    out = []
    for b in batches(rows, bs, False):
        enc, _ = make_batch(tok, b, prefix, max_len, ctx)
        out.append(torch.softmax(model(**{k: v.to(model.device) for k, v in enc.items()}).logits, -1).cpu().numpy())
    return np.concatenate(out) if out else np.zeros((0, len(CATEGORIES)))


def score(model, tok, rows, prefix, max_len, ctx):
    p = predict_proba(model, tok, rows, prefix, max_len, ctx)
    y = [r["category"] for r in rows]
    pred = [CATEGORIES[i] for i in p.argmax(1)]
    m = evaluate(y, pred, CATEGORIES)
    m["calibration"] = calibration_table([float(x.max()) for x in p], [a == b for a, b in zip(y, pred)])
    return m


def latency_ms(model, tok, prefix, max_len, ctx, n=40):
    sample = [{"message": "Amit please integrate Razorpay by Friday", "_prev": "status?", "category": "TASK"}]
    enc, _ = make_batch(tok, sample, prefix, max_len, ctx)
    enc = {k: v.to(model.device) for k, v in enc.items()}
    with torch.inference_mode():
        for _ in range(5):
            model(**enc)
        t = time.perf_counter()
        for _ in range(n):
            model(**enc)
    return (time.perf_counter() - t) / n * 1000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="intfloat/multilingual-e5-small")
    ap.add_argument("--epochs", type=int, default=4)
    ap.add_argument("--lr", type=float, default=5e-5)
    ap.add_argument("--bs", type=int, default=32)
    ap.add_argument("--max-len", type=int, default=64)
    ap.add_argument("--ctx", action="store_true", help="encode previous message as sentence pair")
    ap.add_argument("--max-train", type=int, default=0, help="debug: cap train rows")
    ap.add_argument("--synthetic", default="data/synthetic/gold.jsonl")
    ap.add_argument("--annotations", default="data/annotated/annotations.jsonl")
    ap.add_argument("--probe", default="eval/probe_handwritten.jsonl")
    ap.add_argument("--out", default="models/transformer")
    ap.add_argument("--seed", type=int, default=13)
    a = ap.parse_args()

    random.seed(a.seed); np.random.seed(a.seed); torch.manual_seed(a.seed)
    rng = random.Random(a.seed)
    syn = load(a.synthetic)
    for r in syn:
        r["project_id"] = "S:" + r["project_id"]
    add_context(syn)
    human = add_context([r for r in load(a.annotations) if r.get("source") == "human"])
    probe = add_context(load(a.probe))
    sp = split_projects([r["project_id"] for r in syn], val=0.25, allow_test=False)
    train = [r for r in syn if sp[r["project_id"]] == "train"]
    val = [r for r in syn if sp[r["project_id"]] == "val"]
    real_test = []
    if human:
        rs = split_projects([r["project_id"] for r in human], val=0.2, test=0.2)
        train += [r for r in human if rs[r["project_id"]] == "train"]
        val += [r for r in human if rs[r["project_id"]] == "val"]
        real_test = [r for r in human if rs[r["project_id"]] == "test"]
    if a.max_train:
        rng.shuffle(train)
        train = train[:a.max_train]
    print(f"train={len(train)} val={len(val)} probe={len(probe)} real_test={len(real_test)} device={device()}")

    torch.set_num_threads(os.cpu_count() or 4)
    tok = AutoTokenizer.from_pretrained(a.model)
    model = AutoModelForSequenceClassification.from_pretrained(
        a.model, num_labels=len(CATEGORIES),
        id2label=dict(enumerate(CATEGORIES)), label2id=L2I).to(device())
    prefix = prefix_for(a.model)

    # class-weighted loss (balanced), softened with sqrt to avoid over-boosting rare classes
    counts = np.bincount([L2I[r["category"]] for r in train], minlength=len(CATEGORIES)).clip(min=1)
    w = torch.tensor((counts.sum() / (len(counts) * counts)) ** 0.5, dtype=torch.float, device=model.device)
    loss_fn = torch.nn.CrossEntropyLoss(weight=w)
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=0.01)
    steps = a.epochs * ((len(train) + a.bs - 1) // a.bs)
    sched = get_linear_schedule_with_warmup(opt, int(0.06 * steps), steps)

    best_f1, best_state, history = -1.0, None, []
    t0 = time.time()
    for ep in range(a.epochs):
        model.train()
        tot = 0.0
        for b in batches(train, a.bs, True, rng):
            enc, y = make_batch(tok, b, prefix, a.max_len, a.ctx)
            logits = model(**{k: v.to(model.device) for k, v in enc.items()}).logits
            loss = loss_fn(logits, y.to(model.device))
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step(); sched.step(); opt.zero_grad()
            tot += loss.item() * len(b)
        m = score(model, tok, val, prefix, a.max_len, a.ctx)
        history.append({"epoch": ep + 1, "train_loss": tot / len(train), "val_macro_f1": m["macro_f1"]})
        print(f"epoch {ep + 1}: loss={tot / len(train):.4f} val macroF1={m['macro_f1']:.4f} "
              f"({time.time() - t0:.0f}s)", flush=True)
        if m["macro_f1"] > best_f1:  # selection on validation only
            best_f1, best_state = m["macro_f1"], copy.deepcopy(model.state_dict())
    model.load_state_dict(best_state)

    report = {"base_model": a.model, "context_pair": a.ctx, "history": history,
              "train_seconds": time.time() - t0,
              "SYNTHETIC_ONLY_val": score(model, tok, val, prefix, a.max_len, a.ctx),
              "handwritten_probe": score(model, tok, probe, prefix, a.max_len, a.ctx) if probe else None,
              "REAL_TEST": score(model, tok, real_test, prefix, a.max_len, a.ctx) if real_test else None,
              "params_m": sum(p.numel() for p in model.parameters()) / 1e6,
              "latency_ms_bs1": latency_ms(model, tok, prefix, a.max_len, a.ctx), "device": device()}
    for k in ("SYNTHETIC_ONLY_val", "handwritten_probe", "REAL_TEST"):
        m = report[k]
        print(f"{k}: " + (f"n={m['n']} acc={m['accuracy']:.3f} macroF1={m['macro_f1']:.3f}" if m else "none"))
    print(f"params={report['params_m']:.0f}M latency={report['latency_ms_bs1']:.1f}ms/msg")

    name = a.model.split("/")[-1] + ("_ctx" if a.ctx else "")
    version = f"transformer_{name}_{datetime.now(timezone.utc):%Y%m%d%H%M}"
    report.update(version=version, created_at=datetime.now(timezone.utc).isoformat(), args=vars(a))
    out = Path(a.out) / version
    out.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(out); tok.save_pretrained(out)
    (out / "wa_meta.json").write_text(json.dumps({"labels": CATEGORIES, "base_model": a.model,
        "max_len": a.max_len, "use_context": a.ctx, "version": version}), encoding="utf-8")
    (out / "metrics.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("saved", out)


if __name__ == "__main__":
    main()
