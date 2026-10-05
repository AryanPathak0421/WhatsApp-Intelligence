import json

import httpx
import pytest

from wa_assistant.api import create_app
from wa_assistant.llm.base import LLMOutput
from wa_assistant.llm.scripted import ScriptedLLM, call

pytestmark = pytest.mark.anyio
ALPHA = "11111111-aaaa-4aaa-8aaa-111111111111"


def client(env):
    app = create_app(env.a, env.a.settings)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://assistant")


def H(env, who):
    return {"Authorization": f"Bearer {env.ids['tok_' + who]}"}


async def test_requires_a_token_the_backend_accepts(make_env):
    env = make_env(ScriptedLLM([]))
    async with client(env) as c:
        assert (await c.post("/assistant/chat", json={"message": "hi"})).status_code == 401
        assert (await c.post("/assistant/chat", json={"message": "hi"}, headers={"Authorization": "Bearer nope"})).status_code == 401


async def test_chat_then_confirm_over_http(make_env):
    env = make_env(ScriptedLLM([LLMOutput(tool_calls=[call("list_projects")]), LLMOutput(tool_calls=[call("list_tasks", project_id=ALPHA)]), LLMOutput(text="x")]))
    env.a.agent.llm.outputs.insert(2, LLMOutput(tool_calls=[call("complete_task", task_id=env.ids["t_login"])]))
    async with client(env) as c:
        r = (await c.post("/assistant/chat", json={"message": "finish the login task", "app_state": {"project_id": ALPHA}}, headers=H(env, "pm"))).json()
        assert r["pending"] and env.world.tasks[env.ids["t_login"]]["status"] == "TODO"
        body = {"session_id": r["session_id"], "pending_id": r["pending"][0]["id"]}
        assert (await c.get("/assistant/pending", headers=H(env, "pm"))).json()["items"]
        assert (await c.post("/assistant/confirm", json=body, headers=H(env, "admin"))).status_code == 404      # another user: session does not exist for them
        done = (await c.post("/assistant/confirm", json=body, headers=H(env, "pm"))).json()
        assert done["actions"][0]["status"] == "verified" and env.world.tasks[env.ids["t_login"]]["status"] == "COMPLETED"
        assert (await c.get("/assistant/pending", headers=H(env, "pm"))).json()["items"] == []


async def test_chat_validation_and_unreachable_model(make_env):
    class Down:
        name = "down"

        async def complete(self, *a, **k):
            raise httpx.ConnectError("refused")
    env = make_env(Down())
    async with client(env) as c:
        assert (await c.post("/assistant/chat", json={"message": ""}, headers=H(env, "pm"))).status_code == 422
        r = await c.post("/assistant/chat", json={"message": "hello"}, headers=H(env, "pm"))
        assert r.status_code == 503 and "not reachable" in r.json()["detail"]


async def test_document_upload_permissions_and_search(make_env, tmp_path):
    from wa_assistant.rag.store import DocumentStore
    docs = DocumentStore()
    env = make_env(ScriptedLLM([LLMOutput(tool_calls=[call("search_documents", query="what reduces trainable parameters")]),
                                LLMOutput(text="Small matrices are trained instead [C1].")]), documents=docs)
    paper = (b"# Adapters Paper\n\nAbstract\nTraining small low-rank matrices reduces the number of trainable parameters while the base weights stay frozen "
             b"during adaptation to downstream tasks.\n")
    async with client(env) as c:
        files = {"file": ("adapters.md", paper, "text/markdown")}
        assert (await c.post("/assistant/documents", files=files, data={"year": "2024"}, headers=H(env, "viewer"))).status_code == 403
        assert (await c.post("/assistant/documents", files={"file": ("evil.exe", b"MZ", "application/octet-stream")}, headers=H(env, "admin"))).status_code == 400
        ok = await c.post("/assistant/documents", files=files, data={"year": "2024", "authors": "A. Author; B. Writer"}, headers=H(env, "admin"))
        assert ok.status_code == 201 and ok.json()["chunks"] >= 1
        assert (await c.post("/assistant/documents", files=files, headers=H(env, "admin"))).json()["already_present"] is True
        r = (await c.post("/assistant/chat", json={"message": "what reduces trainable parameters?"}, headers=H(env, "member"))).json()
        assert r["citations"] and r["citations"][0]["authors"] == ["A. Author", "B. Writer"] and "References:" in r["reply"]
        assert (await c.delete(f"/assistant/documents/{ok.json()['id']}", headers=H(env, "pm"))).status_code == 403


async def test_feedback_goes_to_a_review_queue(make_env, tmp_path):
    env = make_env(ScriptedLLM([]), feedback_file=str(tmp_path / "fb.jsonl"))
    async with client(env) as c:
        r = await c.post("/assistant/feedback", json={"turn_id": "abc", "rating": -1, "comment": "wrong project"}, headers=H(env, "pm"))
        assert r.status_code == 200
        assert (await c.post("/assistant/feedback", json={"turn_id": "abc", "rating": 5}, headers=H(env, "pm"))).status_code == 422
    rec = json.loads((tmp_path / "fb.jsonl").read_text().splitlines()[0])
    assert rec["status"] == "needs_review" and rec["rating"] == -1
