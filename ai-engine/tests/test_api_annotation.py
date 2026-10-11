import io

import pytest
from fastapi.testclient import TestClient

from app.annotation.core import AnnotationStore, build_queue, triage

CHAT = ("01/10/2026, 10:30 - Rahul: Amit please integrate Razorpay by Friday.\n"
        "01/10/2026, 10:45 - Amit: Working on it.\n")


@pytest.fixture
def client(tmp_path, monkeypatch):
    import app.api.main as main
    monkeypatch.setattr(main, "store", AnnotationStore(tmp_path / "a.jsonl"))
    return TestClient(main.app)


def test_annotation_validation_and_history(client):
    base = dict(project_id="p", message_id="m1", message="x", category="TASK", reviewer="me")
    assert client.post("/ai/annotation", json=base).status_code == 200
    assert client.post("/ai/annotation", json={**base, "category": "NOPE"}).status_code == 422
    client.post("/ai/annotation", json={**base, "category": "TASK_COMPLETED", "status": "COMPLETED"})
    rows = client.get("/ai/annotation", params={"project_id": "p"}).json()
    assert len(rows) == 1 and rows[0]["category"] == "TASK_COMPLETED"  # latest wins


def test_triage_thresholds():
    assert triage(0.96) == "auto_accept" and triage(0.95) == "review"
    assert triage(0.70) == "review" and triage(0.69) == "annotate"


def test_queue_lowest_confidence_first_skips_labelled():
    preds = [{"project_id": "p", "message_id": str(i), "confidence": c}
             for i, c in enumerate([0.99, 0.5, 0.8, 0.3])]
    q = build_queue(preds, {("p", "3")})
    assert [x["message_id"] for x in q] == ["1", "2"]
    assert [x["queue"] for x in q] == ["annotate", "review"]


def test_analyze_endpoint(client):
    chat = ("01/10/2026, 10:00 - Rahul: Amit please integrate Razorpay by Friday.\n"
            "01/10/2026, 11:00 - Amit: Working on payment.\n"
            "02/10/2026, 11:00 - Amit: Razorpay API integrated.\n")
    r = client.post("/ai/analyze", files={"file": ("c.txt", io.BytesIO(chat.encode()))})
    assert r.status_code == 200
    t = r.json()["tasks"][0]
    assert t["assigned_to"] == "Amit" and t["status"] == "COMPLETED" and t["evidence_message_ids"]


def test_index_search_graph_endpoints(client, monkeypatch):
    import app.api.main as main
    monkeypatch.setattr(main, "_embedder", __import__("app.embeddings.embedder", fromlist=["x"]).HashingEmbedder())
    main._projects.clear()
    body = {"project_id": "P1", "messages": [
        {"id": "m1", "text": "Amit please integrate Razorpay by Friday", "sender": "Rahul", "ts": "2026-10-01T10:00:00"},
        {"id": "m2", "text": "Razorpay API integrated", "sender": "Amit", "ts": "2026-10-02T10:00:00"}]}
    assert client.post("/ai/index", json=body).json()["added"] == 2
    assert client.post("/ai/index", json=body).json()["added"] == 0
    hits = client.post("/ai/search", json={"project_id": "P1", "query": "razorpay", "mode": "lexical"}).json()["hits"]
    assert {h["message_id"] for h in hits} == {"m1", "m2"}
    assert client.post("/ai/search", json={"project_id": "P2", "query": "x"}).status_code == 404
    assert client.post("/ai/search", json={"project_id": "P1", "query": "x", "mode": "bad"}).status_code == 422
    chat = ("01/10/2026, 10:00 - Rahul: Amit please integrate Razorpay by Friday.\n"
            "02/10/2026, 10:00 - Amit: Razorpay API integrated.\n")
    g = client.post("/ai/graph", files={"file": ("c.txt", io.BytesIO(chat.encode()))}).json()
    assert g["graph"]["nodes"] and g["graph"]["edges"]


def test_service_token_and_message_endpoints(client, monkeypatch):
    monkeypatch.setenv("AI_ENGINE_TOKEN", "s3cret")
    assert client.get("/health").status_code == 200  # health stays open
    assert client.post("/ai/analyze-messages", json={"messages": []}).status_code == 401
    h = {"x-service-token": "s3cret"}
    assert client.post("/ai/analyze-messages", json={"messages": []}, headers=h).status_code == 422
    body = {"messages": [
        {"id": "a", "text": "Amit please integrate Razorpay by Friday", "sender": "Rahul", "ts": "2026-10-01T10:00:00", "index": 0},
        {"id": "b", "text": "Razorpay API integrated", "sender": "Amit", "ts": "2026-10-02T10:00:00", "index": 1}],
        "role_overrides": {"Rahul": "PROJECT_MANAGER"}, "meta": {"name": "Shop"}}
    r = client.post("/ai/analyze-messages", json=body, headers=h).json()
    assert r["tasks"][0]["status"] == "COMPLETED" and r["roles"]["Rahul"]["source"] == "admin"
    rep = client.post("/ai/report-messages", json=body, headers=h).json()
    assert rep["meta"]["project"] == "Shop"
    for fmt, magic in (("pdf", b"%PDF"), ("xlsx", b"PK"), ("csv", b"Task"), ("json", b"{")):
        out = client.post("/ai/export", json={"report": rep, "format": fmt}, headers=h)
        assert out.status_code == 200 and out.content.startswith(magic), fmt
