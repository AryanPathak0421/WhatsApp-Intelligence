"""End-to-end Phase-5 intelligence over a parsed chat."""
from __future__ import annotations

import dataclasses
from datetime import datetime
from typing import Optional

from app.analytics.contribution import communication, compute_contribution, sales_activity
from app.analytics.health import compute_health
from app.analytics.progress import compute_progress, progress_timeline, velocity
from app.intelligence.bugs_commitments import detect_bugs, detect_commitments
from app.intelligence.decisions import detect_decisions, detect_meetings
from app.intelligence.client_pending import detect_client_pending
from app.intelligence.completion import apply_project_completion, detect_project_completion
from app.intelligence.conflicts import detect_conflicts
from app.intelligence.qa import detect_qa
from app.intelligence.sentiment import analyze_sentiment
from app.intelligence.requirements import detect_requirements
from app.intelligence.risks import detect_risks
from app.intelligence.roles import infer_roles
from app.intelligence.tasks import build_tasks, task_domain, task_priority, task_weight
from app.intelligence.types import ENGINE_VERSION, Msg
from app.summarization.periodic import build_periodic
from app.knowledge_graph.graph import build_graph, generate_insights, next_actions


def classify_messages(msgs: list[Msg], classifier, prediction_logger=None, project_id: str = "") -> None:
    """Fill msg.category / cat_conf from any classifier exposing .predict(texts, prev).
    If a PredictionLogger is given, each prediction is logged WITHOUT its text (drift monitoring)."""
    if classifier is None or not msgs:
        return
    prev = [None] + [m.text for m in msgs[:-1]]
    preds = classifier.predict([m.text for m in msgs], prev)
    for m, p in zip(msgs, preds):
        m.category, m.cat_conf = p["category"], p["confidence"]
        if prediction_logger is not None:
            prediction_logger.log(project_id, m.id, p["category"], p["confidence"], p.get("model_version", "unknown"))


def _task_dict(t) -> dict:
    d = t.deadline
    return {"id": t.id, "title": t.title, "assigned_to": t.assignee, "created_by": t.created_by,
            "status": t.status, "priority": task_priority(t.title, d, t.created_at),
            "created_at": t.created_at, "domain": task_domain(t.topic, t.title), "weight": task_weight(t.topic, t.title),
            "deadline_text": d.text if d else None, "deadline": d.when if d else None,
            "deadline_confidence": d.confidence if d else None, "completed_at": t.completed_at,
            "external_dependency": t.external_dependency, "confidence": t.confidence,
            "needs_review": t.needs_review or t.confidence < 0.7, "review_reasons": t.review_reasons,
            "source_message_id": t.source_message_id, "evidence_message_ids": t.source_ids(),
            "status_trace": t.status_trace, "evidence": [dataclasses.asdict(e) for e in t.evidence],
            "model_version": t.model_version}


def analyze(msgs: list[Msg], role_overrides: Optional[dict] = None, classifier=None,
            as_of: Optional[datetime] = None, risk_weights: Optional[dict] = None,
            project_start: Optional[datetime] = None, expected_delivery: Optional[datetime] = None,
            health_weights: Optional[dict] = None, progress_credits: Optional[dict] = None,
            linker=None, prediction_logger=None, project_id: str = "") -> dict:
    msgs = [m for m in msgs if m.text is not None]
    classify_messages(msgs, classifier, prediction_logger, project_id)
    as_of = as_of or (msgs[-1].ts if msgs else datetime.utcnow())
    roles = infer_roles(msgs, role_overrides)
    tasks, links = build_tasks(msgs, roles, as_of, linker)
    for t in tasks:  # someone who is assigned work and has no better role evidence is a developer
        r = roles.get(t.assignee)
        if r and r["role"] == "OTHER":
            roles[t.assignee] = {"role": "DEVELOPER", "confidence": 0.5, "source": "assignment"}
    completion = detect_project_completion(msgs, roles)
    closed_by_completion = apply_project_completion(tasks, completion)
    cp_items, response = detect_client_pending(msgs, roles, tasks, links, as_of)
    reqs, req_changes = detect_requirements(msgs, roles)
    bugs = detect_bugs(msgs, roles, tasks)
    commitments = detect_commitments(msgs, roles, tasks, as_of)
    conflicts = detect_conflicts(msgs)
    risk = detect_risks(msgs, tasks, cp_items, bugs, req_changes, conflicts, response, as_of, risk_weights)
    task_dicts = [_task_dict(t) for t in tasks]
    start = project_start or (msgs[0].ts if msgs else as_of)
    progress = compute_progress(task_dicts, cp_items, progress_credits)
    vel = velocity(task_dicts, msgs[0].ts if msgs else as_of, as_of)
    health = compute_health(task_dicts, progress, risk, vel, as_of, start if (project_start and expected_delivery) else None,
                            expected_delivery, health_weights)
    result = {"engine_version": ENGINE_VERSION, "as_of": as_of, "roles": roles,
            "progress": progress, "health": health, "velocity": vel,
            "progress_timeline": progress_timeline(task_dicts, msgs[0].ts if msgs else as_of, as_of, progress_credits),
            "contribution": compute_contribution(task_dicts, bugs, commitments, msgs, roles, as_of),
            "sales": sales_activity(msgs, roles, cp_items), "communication": communication(msgs, task_dicts, as_of),
            "project_completion": completion and {**completion, "closed_task_ids": closed_by_completion},
            "tasks": task_dicts, "message_links": links, "client_pending": cp_items,
            "client_response_time": response, "requirements": reqs, "requirement_changes": req_changes,
            "bugs": bugs, "commitments": commitments, "conflicts": conflicts, "risk": risk,
            "decisions": detect_decisions(msgs, roles), "meetings": detect_meetings(msgs, roles), "qa": detect_qa(msgs, roles, as_of),
            "sentiment": analyze_sentiment(msgs, roles)}
    result["periodic"] = build_periodic(result, msgs)
    G = build_graph(result, msgs)
    result["insights"] = generate_insights(G, as_of)
    result["next_actions"] = next_actions(result, as_of)
    result["graph_stats"] = {"nodes": G.number_of_nodes(), "edges": G.number_of_edges()}
    return result
