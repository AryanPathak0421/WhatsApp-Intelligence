import io
import json

import pytest

from app.annotation.core import AnnotationStore
from app.annotation.prelabel import annotation_stats, build_batch, detect_language, main as prelabel_cli
from app.labels import CATEGORIES

CHAT = """[01/10/2026, 10:00 AM] Rahul (PM): Amit, please integrate Razorpay by Friday.
[01/10/2026, 10:05 AM] Amit: Working on payment.
[01/10/2026, 10:10 AM] Rahul (PM): ok
[01/10/2026, 10:20 AM] Sales - Neha: Waiting for client confirmation for homepage design.
[01/10/2026, 10:25 AM] Karan: Found a bug, cart page crashes on submit
[01/10/2026, 10:40 AM] Rohan: Fixed the cart page bug
[01/10/2026, 10:41 AM] Karan: cart page tested successfully
[02/10/2026, 10:00 AM] Amit: Razorpay API integrated.
[02/10/2026, 10:01 AM] Anjali (Client): Actually client wants PayU instead of Razorpay
[02/10/2026, 10:02 AM] ‎image omitted
[02/10/2026, 10:03 AM] Rahul (PM): Demo call tomorrow at 3 pm?
[02/10/2026, 10:04 AM] This message was deleted
"""


@pytest.fixture(scope="module")
def batch():
    return build_batch(CHAT, "p1", double=0.25, seed=3)


def by_text(batch, needle):
    return next(i for i in batch["items"] if needle in i["message"])


def test_core_categories_and_validity(batch):
    expect = {"integrate Razorpay": "TASK", "Working on payment": "TASK_IN_PROGRESS", "Waiting for client": "CLIENT_PENDING", "crashes on submit": "BUG",
              "Fixed the cart": "BUG_FIXED", "tested successfully": "TESTING", "API integrated": "TASK_COMPLETED", "instead of Razorpay": "REQUIREMENT_CHANGE",
              "Demo call": "MEETING"}
    for needle, cat in expect.items():
        assert by_text(batch, needle)["proposal"]["category"] == cat, needle
    for it in batch["items"]:
        p = it["proposal"]
        assert p["category"] in CATEGORIES and 0.2 <= p["confidence"] <= 0.95 and p["model_version"]
        assert it["lane"] in ("auto_accept", "review", "annotate")


def test_chatter_is_general_and_skips_media_system_deleted(batch):
    assert by_text(batch, "ok")["proposal"]["category"] == "GENERAL"
    texts = " ".join(i["message"] for i in batch["items"])
    assert "omitted" not in texts and "deleted" not in texts
    assert batch["meta"]["messages_total"] == 12 and batch["meta"]["labelable"] == 10


def test_task_structure_is_proposed(batch):
    create = by_text(batch, "integrate Razorpay")["proposal"]
    assert create["assignee"] == "Amit" and create["deadline_text"] == "by Friday" and create["task_key"] == "T1" and create["status"] == "TODO"
    done = by_text(batch, "API integrated")["proposal"]
    assert done["task_key"] == "T1" and done["status"] == "COMPLETED"
    assert by_text(batch, "Waiting for client")["proposal"]["client_pending"] is True


def test_roles_come_from_names_and_context_is_included(batch):
    roles = batch["meta"]["roles_used"]
    assert roles["Anjali (Client)"] == "CLIENT" and roles["Sales - Neha"] == "SALES"
    it = by_text(batch, "Working on payment")
    assert it["context_before"][0]["text"].startswith("Amit, please integrate") and it["context_after"]
    assert by_text(batch, "instead of Razorpay")["proposal"]["sender_role"] == "CLIENT"


def test_queue_order_double_sample_and_determinism(batch):
    confs = [i["proposal"]["confidence"] for i in batch["items"]]
    assert [i["queue_rank"] for i in batch["items"]] == list(range(len(batch["items"])))
    assert confs[0] <= confs[-1] + 0.15                                   # least certain first (rare classes get a small boost)
    again = build_batch(CHAT, "p1", double=0.25, seed=3)
    assert [i["double"] for i in again["items"]] == [i["double"] for i in batch["items"]]
    assert sum(i["double"] for i in batch["items"]) == round(10 * 0.25)


def test_language_detection():
    assert detect_language("मैं समझा नहीं") == "hi"
    assert detect_language("kal tak kar denge, nahi hua abhi") == "hinglish"
    assert detect_language("Please send the link") == "en"


def test_cli_writes_a_batch(tmp_path, capsys):
    src, out = tmp_path / "c.txt", tmp_path / "b.json"
    src.write_text(CHAT, encoding="utf-8")
    prelabel_cli([str(src), str(out), "--project", "px", "--role", "Karan=QA"])
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["meta"]["project_id"] == "px" and data["meta"]["roles_used"]["Karan"] == "QA"
    assert "in queue" in capsys.readouterr().out


def test_proposal_is_kept_and_measured_when_annotator_saves(tmp_path):
    store = AnnotationStore(tmp_path / "a.jsonl")
    from app.annotation.core import AnnotationIn
    base = dict(project_id="p", message="x", reviewer="me")
    store.save(AnnotationIn(message_id="1", category="TASK", proposal={"category": "TASK", "confidence": 0.9}, **base))
    store.save(AnnotationIn(message_id="2", category="BUG", proposal={"category": "TASK", "confidence": 0.9}, **base))
    store.save(AnnotationIn(message_id="3", category="GENERAL", proposal={"category": "DISCUSSION", "confidence": 0.4}, **base))
    store.save(AnnotationIn(message_id="4", category="GENERAL", **base))          # no proposal shown -> not counted
    stats = annotation_stats(list(store.latest().values()))
    assert stats["reviewed"] == 3 and stats["accept_rate"] == pytest.approx(1 / 3, abs=0.001)
    assert stats["per_proposed_category"]["TASK"] == {"shown": 2, "accepted": 1, "rate": 0.5}
    assert stats["accept_rate_by_confidence"][">=0.85"] == {"n": 2, "accepted": 0.5}
    assert annotation_stats([]) == {"reviewed": 0}
    assert "proposal" not in store.history()[0] and store.history()[0]["model_prediction"]["category"] == "TASK"


def test_stats_endpoint(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import app.api.main as main
    monkeypatch.setattr(main, "store", AnnotationStore(tmp_path / "a.jsonl"))
    c = TestClient(main.app)
    r = c.post("/ai/annotation", json={"project_id": "p", "message_id": "m", "message": "x", "category": "TASK", "reviewer": "me",
                                       "proposal": {"category": "TASK", "confidence": 0.8}})
    assert r.status_code == 200
    s = c.get("/ai/annotation/stats", params={"project_id": "p"}).json()
    assert s["reviewed"] == 1 and s["accept_rate"] == 1.0


def test_per_reviewer_export_supports_double_annotation(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import app.api.main as main
    from app.evaluation.agreement import compare, load
    monkeypatch.setattr(main, "store", AnnotationStore(tmp_path / "a.jsonl"))
    c = TestClient(main.app)
    for reviewer, cats in (("ann_a", ["TASK", "BUG", "GENERAL"]), ("ann_b", ["TASK", "BUG", "QUESTION"])):
        for i, cat in enumerate(cats):
            assert c.post("/ai/annotation", json={"project_id": "p", "message_id": f"m{i}", "message": "x", "category": cat, "reviewer": reviewer}).status_code == 200
    files = {}
    for r in ("ann_a", "ann_b"):
        text = c.get("/ai/annotation/export", params={"reviewer": r, "project_id": "p"}).text
        assert len(text.splitlines()) == 3                     # each reviewer keeps their OWN labels (latest() would keep only the last writer)
        files[r] = tmp_path / f"{r}.jsonl"
        files[r].write_text(text, encoding="utf-8")
    res = compare(load(files["ann_a"]), load(files["ann_b"]))
    assert res["n_overlap"] == 3 and res["agreement"] == pytest.approx(2 / 3, abs=0.01)


def test_server_side_batches_are_listed_and_path_traversal_is_blocked(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import app.api.main as main
    (tmp_path / "ok.json").write_text(json.dumps({"meta": {"project_id": "p"}, "items": []}))
    (tmp_path / "secret.txt").write_text("nope")
    (tmp_path.parent / "outside.json").write_text("{}")
    monkeypatch.setenv("ANNOTATION_BATCH_DIR", str(tmp_path))
    c = TestClient(main.app)
    assert c.get("/ai/annotation/batches").json() == {"items": ["ok.json"]}
    assert c.get("/ai/annotation/batches/ok.json").json()["meta"]["project_id"] == "p"
    for bad in ("secret.txt", "..%2Foutside.json", "%2E%2E%2Foutside.json", "nothere.json", "..\outside.json"):
        assert c.get(f"/ai/annotation/batches/{bad}").status_code in (404, 422), bad
    monkeypatch.delenv("ANNOTATION_BATCH_DIR")
    assert c.get("/ai/annotation/batches").json() == {"items": []}


@pytest.mark.parametrize("sender_lines,expected", [
    (["Rahul: Please share the Figma link", "Priya: दूसरा अपना 10 + 1 मंथली plans रहेगा", "Priya: ऑफर का ऑप्शन भी रहना चाहिए"], "REQUIREMENT"),
    (["Priya: क्योंकि मुझे सब पहले जैसा ही नहीं दिख रहा है", "Priya: Madam, the filter is the same old one as it was."], "CLIENT_FEEDBACK"),
])
def test_hinglish_and_devanagari_client_messages_are_not_left_as_discussion(sender_lines, expected):
    chat = "\n".join(f"01/06/2026, 10:{i:02d} - {l}" for i, l in enumerate(sender_lines))
    b = build_batch(chat, "p", {"Priya": "CLIENT", "Rahul": "DEVELOPER"})
    got = [i["proposal"]["category"] for i in b["items"] if i["message"] != "Please share the Figma link"]
    assert expected in got and "DISCUSSION" not in got


def test_developer_asking_the_client_to_check_or_send_is_client_pending():
    chat = "01/06/2026, 10:00 - Rahul: Aap ek baar go through krlo full website\n01/06/2026, 10:01 - Priya: ok"
    b = build_batch(chat, "p", {"Priya": "CLIENT", "Rahul": "DEVELOPER"})
    assert b["items"][0]["proposal"]["category"] == "CLIENT_PENDING"


def test_hinglish_done_and_payment_forms():
    chat = ("01/06/2026, 10:00 - Rahul: changes sare hogye h website pr\n"
            "01/06/2026, 10:01 - Rahul: 10k sms price is 2242rs\n01/06/2026, 10:02 - Priya: ok")
    cats = [i["proposal"]["category"] for i in sorted(build_batch(chat, "p", {"Priya": "CLIENT", "Rahul": "DEVELOPER"})["items"], key=lambda i: i["index"])]
    assert cats[0] == "TASK_COMPLETED" and cats[1] == "PAYMENT"


def test_task_pending_is_merged_into_task(tmp_path):
    from app.annotation.core import AnnotationIn
    from app.labels import ACTIVE_CATEGORIES, canonical
    assert "TASK_PENDING" not in ACTIVE_CATEGORIES and canonical("TASK_PENDING") == "TASK"
    store = AnnotationStore(tmp_path / "a.jsonl")
    a = AnnotationIn(project_id="p", message_id="m1", message="abhi pending hai", category="TASK_PENDING", reviewer="r",
                     proposal={"category": "TASK_PENDING", "confidence": 0.5})
    assert a.category == "TASK"
    store.save(a)
    with (tmp_path / "a.jsonl").open("a", encoding="utf-8") as fh:        # a record written before the merge
        fh.write(json.dumps({"project_id": "p", "message_id": "m2", "category": "TASK_PENDING", "reviewer": "r",
                             "model_prediction": {"category": "TASK_PENDING", "confidence": 0.5}}) + "\n")
    assert [r["category"] for r in store.history()] == ["TASK", "TASK"]
    assert all(r["model_prediction"]["category"] == "TASK" for r in store.history())
    chat = "01/06/2026, 10:00 - Rahul: login page abhi pending hai\n01/06/2026, 10:01 - Priya: ok"
    assert all(i["proposal"]["category"] != "TASK_PENDING" for i in build_batch(chat, "p", {})["items"])
