"""Evaluate the engines on unseen, hand-written, realistic chats (eval/unseen/*.txt + *.gold.json).

    python -m bench.unseen_eval [--verbose]

These chats were written independently of the generator and NOT used to tune any rule when first measured,
but the author is also the rules' author, so treat the numbers as optimistic. Failures are printed on purpose.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from app.intelligence.pipeline import analyze
from app.intelligence.types import Msg
from app.parsers.whatsapp import WhatsAppParser

DIR = Path(__file__).resolve().parent.parent / "eval" / "unseen"


def first(n):
    return (n or "").split()[0].lower() if n else None


def evaluate(chat_path: Path, gold: dict, verbose=False):
    parsed = WhatsAppParser().parse_text(chat_path.read_text(encoding="utf-8"))
    by_id = {m.message_id: m for m in parsed}
    res = analyze([Msg.from_parsed(m) for m in parsed])
    rep = {"file": chat_path.name, "messages": len(parsed), "fails": [], "tasks_pred": [(t["title"], t["assigned_to"], t["status"]) for t in res["tasks"]]}
    c = dict(task_gold=0, task_found=0, task_assignee_ok=0, task_status_ok=0, pred_tasks=len(res["tasks"]), pred_matched=0,
             cp_gold=0, cp_found=0, cp_status_ok=0, pred_cp=len(res["client_pending"]), cp_matched=0,
             rc_gold=len(gold["requirement_changes"]), rc_found=0, bug_gold=len(gold["bugs"]), bug_found=0, bug_status_ok=0,
             dec_gold=len(gold.get("decisions", [])), dec_found=0, conf_chats=int("conflicts" in gold), conf_ok=0)
    used = set()
    for g in gold["tasks"]:
        c["task_gold"] += 1
        hit = next((t for t in res["tasks"] if t["id"] not in used and all(k in t["title"].lower() for k in g["keywords"])), None)
        if not hit:
            rep["fails"].append(f"TASK missed: {g['keywords']} ({g['assignee']}, {g['status']})")
            continue
        used.add(hit["id"]); c["task_found"] += 1; c["pred_matched"] += 1
        if g["assignee"] is None or first(hit["assigned_to"]) == first(g["assignee"]):
            c["task_assignee_ok"] += 1
        else:
            rep["fails"].append(f"TASK assignee: {g['keywords']} gold={g['assignee']} got={hit['assigned_to']}")
        if hit["status"] == g["status"]:
            c["task_status_ok"] += 1
        else:
            rep["fails"].append(f"TASK status: {g['keywords']} gold={g['status']} got={hit['status']} reasons={hit['review_reasons']}")
    cp_used = set()
    for g in gold["client_pending"]:
        c["cp_gold"] += 1
        def text_of(it):
            return (it["title"] + " " + " ".join(by_id[i].text for i in it["source_message_ids"] if i in by_id)).lower()
        hit = next((it for it in res["client_pending"] if it["id"] not in cp_used and all(k in text_of(it) for k in g["keywords"])), None)
        if not hit:
            rep["fails"].append(f"CLIENT_PENDING missed: {g['keywords']} ({g['status']})")
            continue
        cp_used.add(hit["id"]); c["cp_found"] += 1; c["cp_matched"] += 1
        if hit["status"] == g["status"]:
            c["cp_status_ok"] += 1
        else:
            rep["fails"].append(f"CLIENT_PENDING status: {g['keywords']} gold={g['status']} got={hit['status']}")
    for g in gold["requirement_changes"]:
        if any(g["old"] in (ch["old_value"] or "").lower() and g["new"] in (ch["new_value"] or "").lower() for ch in res["requirement_changes"]):
            c["rc_found"] += 1
        else:
            rep["fails"].append(f"REQ_CHANGE missed: {g['old']} -> {g['new']}")
    rc_extra = [ch for ch in res["requirement_changes"] if not any(ch["old_value"] == g["old"] and ch["new_value"] == g["new"] for g in gold["requirement_changes"])]
    for g in gold["bugs"]:
        hit = next((b for b in res["bugs"] if all(k in b["title"].lower() for k in g["keywords"])), None)
        if not hit:
            rep["fails"].append(f"BUG missed: {g['keywords']}")
            continue
        c["bug_found"] += 1
        if hit["status"] in g["final"]:
            c["bug_status_ok"] += 1
        else:
            rep["fails"].append(f"BUG status: {g['keywords']} gold={g['final']} got={hit['status']}")
    for g in gold.get("decisions", []):
        if any(all(k in d["title"].lower() for k in g["keywords"]) for d in res["decisions"]):
            c["dec_found"] += 1
        else:
            rep["fails"].append(f"DECISION missed: {g['keywords']}")
    if "conflicts" in gold:
        if len(res["conflicts"]) == gold["conflicts"]:
            c["conf_ok"] += 1
        else:
            rep["fails"].append(f"CONFLICTS: gold={gold['conflicts']} got={len(res['conflicts'])}")
    rep["extra_pred_tasks"] = [x for x in rep["tasks_pred"] if not any(all(k in x[0].lower() for k in g["keywords"]) for g in gold["tasks"])]
    rep["extra_req_changes"] = [(ch["old_value"], ch["new_value"]) for ch in rc_extra]
    rep["extra_bugs"] = [b["title"] for b in res["bugs"] if not any(all(k in b["title"].lower() for k in g["keywords"]) for g in gold["bugs"])]
    rep["counts"] = c
    return rep


def summarize(title, tot):
    pct = lambda a, b: f"{100 * a / b:.0f}%" if b else "n/a"  # noqa: E731
    print(f"\n== {title}")
    print(f"   task recall {pct(tot['task_found'], tot['task_gold'])} ({tot['task_found']}/{tot['task_gold']}), task precision lower bound {pct(tot['pred_matched'], tot['pred_tasks'])} ({tot['pred_matched']}/{tot['pred_tasks']})")
    print(f"   assignee accuracy {pct(tot['task_assignee_ok'], tot['task_gold'])}, final-status accuracy {pct(tot['task_status_ok'], tot['task_gold'])}")
    print(f"   client-pending recall {pct(tot['cp_found'], tot['cp_gold'])}, open/resolved state accuracy {pct(tot['cp_status_ok'], tot['cp_gold'])}")
    print(f"   requirement-change recall {pct(tot['rc_found'], tot['rc_gold'])}, bug recall {pct(tot['bug_found'], tot['bug_gold'])}, bug final-state {pct(tot['bug_status_ok'], tot['bug_gold'])}")
    print(f"   decision recall {pct(tot['dec_found'], tot['dec_gold'])}, conflict-count correct {pct(tot['conf_ok'], tot['conf_chats'])}")


GROUPS = [("TUNED, round 1 (a-c: failures were used to improve the rules)", ("a_", "b_", "c_")),
          ("TUNED, round 2 (d-e: failures were used to improve the rules)", ("d_", "e_")),
          ("FRESH HOLDOUT (f: written after those fixes, run before any tuning on it)", ("f_",))]


def main():
    verbose = "--verbose" in sys.argv
    totals = {title: {} for title, _ in GROUPS}
    for chat in sorted(DIR.glob("*.txt")):
        gold = json.loads(chat.with_suffix(".gold.json").read_text(encoding="utf-8"))
        r = evaluate(chat, gold, verbose)
        c = r["counts"]
        title = next((t for t, prefixes in GROUPS if chat.name.startswith(prefixes)), GROUPS[-1][0])
        for k, v in c.items():
            totals[title][k] = totals[title].get(k, 0) + v
        print("\n== " + r["file"] + f" ({r['messages']} msgs)")
        print(f"   tasks found {c['task_found']}/{c['task_gold']}, assignee ok {c['task_assignee_ok']}, final status ok {c['task_status_ok']}; "
              f"client-pending found {c['cp_found']}/{c['cp_gold']} (state ok {c['cp_status_ok']}); req changes {c['rc_found']}/{c['rc_gold']}; bugs {c['bug_found']}/{c['bug_gold']} (final ok {c['bug_status_ok']})")
        for f in r["fails"]:
            print("   FAIL", f)
        if r["extra_pred_tasks"] or verbose:
            print("   extra predicted tasks (not in gold, may be legitimate):", r["extra_pred_tasks"])
        if r["extra_req_changes"]:
            print("   extra requirement changes:", r["extra_req_changes"])
        if r["extra_bugs"]:
            print("   extra bugs:", r["extra_bugs"])
    for title, tot in totals.items():
        if tot:
            summarize(title, tot)


if __name__ == "__main__":
    main()
