"""Project knowledge graph (NetworkX) built from structured analysis results + insight / action generation.

Nodes: Person, Task, ClientPending, Requirement, Bug, Decision, Meeting, Message (only messages that are cited as evidence).
Edges: ASSIGNED_TO, CREATED, COMPLETED, BLOCKED_BY, DEPENDS_ON, REQUESTED_FROM, REPORTED, AFFECTS, CHANGED, DECIDED, SUPPORTS.
Every edge carries confidence + the message ids it came from. Insights are rendered from graph paths, not generated freely.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import networkx as nx

from app.intelligence.rules import client_pending_type
from app.intelligence.topics import topic_overlap, topic_set

TYPE_LABEL = {"CREDENTIALS": "client credentials", "APPROVAL": "client approval", "UAT": "UAT approval",
              "PAYMENT": "client payment", "CONTENT": "client content", "FEEDBACK": "client feedback",
              "REQUIREMENT": "requirement clarification", "OTHER": "a client response"}


def build_graph(result: dict, msgs, project_id: str = "project") -> nx.MultiDiGraph:
    G = nx.MultiDiGraph(project_id=project_id)
    sender = {m.id: m for m in msgs}

    def node(nid, kind, **attrs):
        if nid not in G:
            G.add_node(nid, kind=kind, **attrs)
        return nid

    def edge(a, b, rel, conf=1.0, ids=()):
        G.add_edge(a, b, rel=rel, confidence=round(conf, 2), source_message_ids=list(ids))

    def support(nid, ids, conf=1.0):
        for mid in ids:
            m = sender.get(mid)
            if m is None:
                continue
            node(f"msg:{mid}", "Message", text=m.text, sender=m.sender, ts=m.ts)
            edge(f"msg:{mid}", nid, "SUPPORTS", conf, [mid])

    for name, r in result["roles"].items():
        node(f"person:{name}", "Person", name=name, role=r["role"])
    for t in result["tasks"]:
        tid = node(f"task:{t['id']}", "Task", title=t["title"], status=t["status"], weight=t["weight"],
                   confidence=t["confidence"], deadline=t["deadline"],
                   external_dependency=t["external_dependency"])
        if t["assigned_to"]:
            edge(f"person:{node('person:' + t['assigned_to'], 'Person', name=t['assigned_to'], role='OTHER')[7:]}", tid,
                 "ASSIGNED_TO", t["confidence"], [t["source_message_id"]])
        if t["created_by"]:
            edge(f"person:{t['created_by']}", tid, "CREATED", 1.0, [t["source_message_id"]])
        if t["status"] == "COMPLETED":
            done = next((tr for tr in reversed(t["status_trace"]) if tr["status"] == "COMPLETED"), None)
            m = sender.get(done["message_id"]) if done else None
            if m and m.sender:
                edge(f"person:{m.sender}", tid, "COMPLETED", t["confidence"], [m.id])
        support(tid, t["evidence_message_ids"], t["confidence"])
    for c in result["client_pending"]:
        cid = node(f"cp:{c['id']}", "ClientPending", title=c["title"], type=c["type"], status=c["status"],
                   age_days=c["age_days"])
        support(cid, c["source_message_ids"], c["confidence"])
        if c["task_id"] and f"task:{c['task_id']}" in G and c["status"] == "OPEN":
            edge(f"task:{c['task_id']}", cid, "BLOCKED_BY", c["confidence"], c["source_message_ids"])
        if c["requested_by"]:
            edge(cid, f"person:{c['requested_by']}", "REQUESTED_FROM", c["confidence"], c["source_message_ids"][:1])
    for r in result["requirements"]:
        rid = node(f"req:{r['key']}", "Requirement", key=r["key"], value=r["versions"][-1]["value"], versions=len(r["versions"]))
        for v in r["versions"]:
            support(rid, [v["message_id"]], v["confidence"])
            if v["changed_by"] and f"person:{v['changed_by']}" in G:
                edge(f"person:{v['changed_by']}", rid, "CHANGED" if v["version"] > 1 else "REQUESTED", v["confidence"], [v["message_id"]])
    for b in result["bugs"]:
        bid = node(f"bug:{b['id']}", "Bug", title=b["title"], status=b["status"])
        support(bid, b["source_message_ids"], b["confidence"])
        if b["reported_by"]:
            edge(f"person:{b['reported_by']}", bid, "REPORTED", b["confidence"], b["source_message_ids"][:1])
        if b["task_id"] and f"task:{b['task_id']}" in G:
            edge(bid, f"task:{b['task_id']}", "AFFECTS", 0.6, b["source_message_ids"][:1])
    for d in result.get("decisions", []):
        did = node(f"dec:{d['id']}", "Decision", title=d["title"], at=d["decided_at"])
        support(did, d["source_message_ids"], d["confidence"])
        edge(f"person:{d['decided_by']}", did, "DECIDED", d["confidence"], d["source_message_ids"])
    for mt in result.get("meetings", []):
        mid = node(f"meet:{mt['id']}", "Meeting", title=mt["title"], at=mt["scheduled_at"])
        support(mid, mt["source_message_ids"], mt["confidence"])
    # task dependencies: a blocked task whose blocking message talks about another task's topic
    tasks_by_id = {t["id"]: t for t in result["tasks"]}
    for t in result["tasks"]:
        if t["status"] != "BLOCKED" or (t["external_dependency"] or "").startswith("CLIENT"):
            continue
        for ev in t["evidence"]:
            if ev["signal"] != "blocked" or ev["message_id"] not in sender:
                continue
            mt = topic_set(sender[ev["message_id"]].text, extra_stop=set(topic_set(t["title"])))
            for o in result["tasks"]:
                if o["id"] != t["id"] and topic_overlap(mt, topic_set(o["title"])) >= 0.6:
                    edge(f"task:{t['id']}", f"task:{o['id']}", "DEPENDS_ON", 0.5, [ev["message_id"]])
    return G


# -------------------------------------------------------------------------------- insights
def explain_blocked(G: nx.MultiDiGraph, task_node: str) -> Optional[dict]:
    """Render 'X is blocked because Y' from graph edges only."""
    data = G.nodes[task_node]
    if data["status"] != "BLOCKED":
        return None
    reasons, ids = [], []
    for _, cp, k, ed in G.out_edges(task_node, keys=True, data=True):
        if ed["rel"] == "BLOCKED_BY":
            cd = G.nodes[cp]
            label = TYPE_LABEL.get(cd["type"], "a client response")
            reasons.append(f"pending {label} ({cd['age_days']:.0f} days)")
            ids += ed["source_message_ids"]
        elif ed["rel"] == "DEPENDS_ON":
            reasons.append(f"a dependency on '{G.nodes[cp]['title']}'")
            ids += ed["source_message_ids"]
    dep = data.get("external_dependency")
    if not reasons and dep and not dep.startswith("CLIENT"):
        reasons.append(f"an unresolved dependency ({dep})")
        ids += [src[4:] for src, _, ed in G.in_edges(task_node, data=True) if ed["rel"] == "SUPPORTS"][:2]
    if not reasons:
        reasons.append("an external dependency that was reported in the chat")
        ids += [src[4:] for src, _, ed in G.in_edges(task_node, data=True) if ed["rel"] == "SUPPORTS"][:1]
    return {"task": data["title"], "text": f"{data['title']} is blocked by " + " and ".join(reasons) + ".",
            "source_message_ids": list(dict.fromkeys(ids))}


def generate_insights(G: nx.MultiDiGraph, as_of: datetime) -> list[dict]:
    out = []
    for n, d in G.nodes(data=True):
        if d["kind"] == "Task":
            e = explain_blocked(G, n)
            if e:
                out.append({"kind": "BLOCKER", **e, "graph_path": [n]})
            if d["status"] not in ("COMPLETED", "CANCELLED") and d.get("deadline") and d["deadline"] < as_of:
                owners = [G.nodes[u]["name"] for u, _, ed in G.in_edges(n, data=True) if ed["rel"] == "ASSIGNED_TO"]
                out.append({"kind": "OVERDUE", "text": f"{d['title']} is overdue (due {d['deadline']:%d %b})"
                            + (f"; owner {owners[0]}." if owners else "."), "source_message_ids": [], "graph_path": [n]})
    for n, d in G.nodes(data=True):
        if d["kind"] == "Requirement" and d["versions"] > 1:
            ids = [src[4:] for src, _, ed in G.in_edges(n, data=True) if ed["rel"] == "SUPPORTS"]
            out.append({"kind": "REQUIREMENT_CHANGE", "text": f"Requirement '{d['key']}' changed {d['versions'] - 1} time(s); current value: {d['value']}.",
                        "source_message_ids": ids, "graph_path": [n]})
    return out


def next_actions(result: dict, as_of: datetime) -> list[dict]:
    """Structured actions from unresolved dependencies (no free text generation)."""
    acts = []
    by_task = {t["id"]: t for t in result["tasks"]}
    sales = {s["person"] for s in result["sales"]}
    for c in result["client_pending"]:
        if c["status"] != "OPEN":
            continue
        owner = c["requested_by"] if c["requested_by"] in sales else next(iter(sales), c["requested_by"])
        t = by_task.get(c["task_id"])
        label = TYPE_LABEL.get(c["type"], "a client response")
        acts.append({"action": f"Follow up with the client for {label}" + (f" ({t['title']})" if t else f" ({c['title']})"),
                     "owner": owner, "priority": c["priority"], "deadline": "today" if c["age_days"] >= 2 else "this week",
                     "source_message_ids": c["source_message_ids"][:3], "reason": f"waiting {c['age_days']:.0f} days",
                     "confidence": c["confidence"]})
    for t in result["tasks"]:
        if t["status"] in ("COMPLETED", "CANCELLED"):
            continue
        if t["deadline"] and t["deadline"] < as_of:
            acts.append({"action": f"Get an updated ETA for {t['title']}", "owner": t["assigned_to"] or t["created_by"],
                         "priority": "HIGH" if t["weight"] >= 3 else "MEDIUM", "deadline": "today",
                         "source_message_ids": t["evidence_message_ids"][:3], "reason": f"overdue since {t['deadline']:%d %b}",
                         "confidence": t["confidence"]})
        elif t["status"] == "TODO" and not t["assigned_to"]:
            acts.append({"action": f"Assign an owner to {t['title']}", "owner": t["created_by"], "priority": "MEDIUM",
                         "deadline": "this week", "source_message_ids": t["evidence_message_ids"][:2],
                         "reason": "no assignee identified", "confidence": t["confidence"]})
    for cf in result["conflicts"]:
        acts.append({"action": f"Verify conflicting statements about {cf['topic']}", "owner": None, "priority": cf["severity"],
                     "deadline": "today", "source_message_ids": cf["source_message_ids"],
                     "reason": "potential contradiction", "confidence": cf["confidence"]})
    order = {"CRITICAL": 3, "HIGH": 2, "MEDIUM": 1, "LOW": 0}
    return sorted(acts, key=lambda a: -order.get(a["priority"], 0))


def to_node_link(G: nx.MultiDiGraph) -> dict:
    return nx.node_link_data(G, edges="edges")
