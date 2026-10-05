"""Score the Phase-5 engines against gold labels.

    python -m app.evaluation.eval_intelligence --chats data/synthetic/chats --gold data/synthetic/gold.jsonl

SYNTHETIC gold only measures regression / template coverage - NOT real-world accuracy.
Point --gold at human-annotated real projects (same schema) for honest numbers.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from app.intelligence.pipeline import analyze
from app.intelligence.types import Msg
from app.parsers.whatsapp import WhatsAppParser


def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {"precision": round(p, 3), "recall": round(r, 3), "f1": round(2 * p * r / (p + r), 3) if p + r else 0.0,
            "tp": tp, "fp": fp, "fn": fn}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chats", default="data/synthetic/chats")
    ap.add_argument("--gold", default="data/synthetic/gold.jsonl")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    gold = defaultdict(list)
    for line in Path(a.gold).open(encoding="utf-8"):
        r = json.loads(line)
        gold[r["project_id"]].append(r)

    c = defaultdict(int)
    for n, (pid, rows) in enumerate(sorted(gold.items())):
        if a.limit and n >= a.limit:
            break
        parsed = WhatsAppParser().parse_text((Path(a.chats) / f"{pid}.txt").read_text(encoding="utf-8"))
        msgs = [Msg.from_parsed(m) for m in parsed]
        res = analyze(msgs)
        idx_of = {m.id: m.index for m in msgs}
        g_task_idx = {r["index"]: r for r in rows if r["category"] == "TASK"}
        got = {idx_of[t["source_message_id"]]: t for t in res["tasks"]}
        # task detection
        c["task_tp"] += len(set(got) & set(g_task_idx))
        c["task_fp"] += len(set(got) - set(g_task_idx))
        c["task_fn"] += len(set(g_task_idx) - set(got))
        # attribute accuracy on matched tasks
        final = {}
        for r in rows:
            if r.get("task_key") and r.get("status"):
                final[r["task_key"]] = r["status"]
        for i in set(got) & set(g_task_idx):
            g, t = g_task_idx[i], got[i]
            c["assignee_n"] += 1
            c["assignee_ok"] += int(t["assigned_to"] == g["assignee"])
            c["deadline_n"] += 1
            c["deadline_ok"] += int(bool(t["deadline_text"]) and (g["deadline_text"] or "").lower().split()[0] in t["deadline_text"].lower())
            gs = final.get(g["task_key"])
            if gs:
                c["status_n"] += 1
                c["status_ok"] += int(t["status"] == gs)
                c["status_completed_gold"] += int(gs == "COMPLETED")
                c["status_completed_false_positive"] += int(t["status"] == "COMPLETED" and gs != "COMPLETED")
        # client pending
        g_cp = {r["index"] for r in rows if r["category"] == "CLIENT_PENDING"}
        got_cp = {idx_of[mid] for it in res["client_pending"] for mid in it["source_message_ids"][:1]}
        c["cp_tp"] += len(g_cp & got_cp); c["cp_fp"] += len(got_cp - g_cp); c["cp_fn"] += len(g_cp - got_cp)
        # requirement changes: explicit "X instead of Y" (first occurrence per project; later repeats are
        # no-ops because the requirement already has that value) and generic scope changes
        g_rc_all = [r for r in rows if r["category"] == "REQUIREMENT_CHANGE"]
        expl = [r["index"] for r in g_rc_all if "instead of" in r["message"].lower() or "ki jagah" in r["message"].lower()]
        g_expl = set(expl[:1])
        g_generic = {r["index"] for r in g_rc_all} - set(expl)
        got_rc = {idx_of[ch["source_message_ids"][0]] for ch in res["requirement_changes"]}
        c["rc_tp"] += len(g_expl & got_rc); c["rc_fn"] += len(g_expl - got_rc)
        c["rc_fp"] += len(got_rc - {r["index"] for r in g_rc_all})
        c["rcg_n"] += len(g_generic); c["rcg_ok"] += len(g_generic & got_rc)
        # bugs
        g_bug = {r["index"] for r in rows if r["category"] == "BUG"}
        got_bug = {idx_of[b["source_message_ids"][0]] for b in res["bugs"]}
        c["bug_tp"] += len(g_bug & got_bug); c["bug_fp"] += len(got_bug - g_bug); c["bug_fn"] += len(g_bug - got_bug)
        c["projects"] += 1

    out = {
        "projects": c["projects"],
        "task_detection": prf(c["task_tp"], c["task_fp"], c["task_fn"]),
        "assignee_accuracy": round(c["assignee_ok"] / max(1, c["assignee_n"]), 3),
        "deadline_accuracy": round(c["deadline_ok"] / max(1, c["deadline_n"]), 3),
        "final_status_accuracy": round(c["status_ok"] / max(1, c["status_n"]), 3),
        "completed_false_positive_rate": round(c["status_completed_false_positive"] / max(1, c["status_n"] - c["status_completed_gold"]), 3),
        "client_pending": prf(c["cp_tp"], c["cp_fp"], c["cp_fn"]),
        "requirement_change_explicit_first": prf(c["rc_tp"], c["rc_fp"], c["rc_fn"]),
        "requirement_change_generic_recall": round(c["rcg_ok"] / max(1, c["rcg_n"]), 3),
        "bug_detection": prf(c["bug_tp"], c["bug_fp"], c["bug_fn"]),
        "WARNING": "gold is SYNTHETIC; measures template coverage, not real-world accuracy",
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
