"""Contract check against the REAL backend (not the sandbox): scripted model, real HTTP, real database.

    python scripts/live_smoke.py --email admin@local.test --password-file ../private-data/dev-admin.txt

Creates a project named 'Assistant smoke test <time>' in the target database (there is no delete tool, by design) and exercises one read, T1 writes
with read-back verification, a T2 confirmation, a T3 refusal and a permission failure. Run it only against a development database.
"""
import argparse
import asyncio
import json
import re
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from wa_assistant.backend import BackendClient          # noqa: E402
from wa_assistant.config import Settings                # noqa: E402
from wa_assistant.factory import build_assistant        # noqa: E402
from wa_assistant.llm.base import LLMOutput             # noqa: E402
from wa_assistant.llm.scripted import ScriptedLLM, call  # noqa: E402


def last_tool_json(msgs):
    for m in reversed(msgs):
        if m["role"] == "tool":
            return json.loads(m["content"])
    return {}


def first_id(msgs, key="items", pick=lambda x: True):
    d = last_tool_json(msgs).get("data") or {}
    if isinstance(d, str):                                    # untrusted results arrive wrapped: <untrusted_data>{json}</untrusted_data>
        d = json.loads(d.removeprefix("<untrusted_data>").removesuffix("</untrusted_data>"))
    return next(x["id"] for x in (d.get(key) or []) if pick(x))


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="http://localhost:4000/api")
    ap.add_argument("--email", required=True)
    ap.add_argument("--password-file", required=True)
    a = ap.parse_args()
    pw = re.search(r"^password: (.+)$", Path(a.password_file).read_text(), re.M).group(1).strip()
    backend = BackendClient(a.backend)
    login = await backend.request("POST", "/auth/login", "", json={"email": a.email, "password": pw})
    assert login.ok, f"login failed: {login.status}"
    token = login.data["accessToken"]
    name = f"Assistant smoke test {time.strftime('%H%M%S')}"
    proj = {}

    def remember_project(msgs):
        proj["id"] = first_id(msgs, pick=lambda x: x["name"] == name)
        return LLMOutput(tool_calls=[call("create_task", project_id=proj["id"], title="Smoke test task", priority="HIGH", deadline="2026-12-31")])

    def list_tasks(msgs):
        return LLMOutput(tool_calls=[call("list_tasks", project_id=proj["id"])])

    def complete(msgs):
        proj["task"] = first_id(msgs)
        return LLMOutput(tool_calls=[call("complete_task", task_id=proj["task"])])

    script = [LLMOutput(tool_calls=[call("create_project", name=name, client_name="Smoke Co")]), LLMOutput(tool_calls=[call("list_projects")]),
              remember_project, list_tasks, complete,
              LLMOutput(tool_calls=[call("delete_task", task_id="x")]), LLMOutput(text="I cannot do that from chat.")]
    with tempfile.TemporaryDirectory() as tmp:
        A = build_assistant(ScriptedLLM(script), backend, Settings(), None, audit_path=f"{tmp}/audit.jsonl")
        me = await backend.request("GET", "/auth/me", token)
        u = me.data["user"]
        s = A.sessions.get_or_create(None, u["id"], u["role"], token)
        r1 = await A.agent.run_turn(s, "create the smoke test project, add a task and complete it")
        print("turn 1 actions:", [(x["tool"], x["status"]) for x in r1.actions], "| pending:", [p["tool"] for p in r1.pending])
        assert r1.pending and r1.pending[0]["tool"] == "complete_task"
        r2 = await A.agent.confirm(s, r1.pending[0]["id"])
        print("confirm:", [(x["tool"], x["status"], x.get("detail")) for x in r2.actions])
        r3 = await A.agent.run_turn(s, "delete that task")
        print("T3:", [(x["tool"], x["status"]) for x in r3.actions])
        listing = await backend.request("GET", f"/projects/{proj['id']}/tasks", token)
        row = listing.data["items"][0]
        print("backend state:", {k: row[k] for k in ("title", "status", "priority")}, "deadline", str(row["deadline"])[:10])
        ok = (r1.actions[0]["status"] == "verified" and r2.actions[0]["status"] == "verified" and row["status"] == "COMPLETED"
              and r3.actions and r3.actions[0]["status"] == "refused" and str(row["deadline"])[:10] == "2026-12-31")
        print("LIVE SMOKE:", "PASS" if ok else "FAIL")
        for e in A.audit.read():
            if e["event"] in ("write_result", "pending_created", "confirmed"):
                print("  audit:", e["event"], e.get("tool"), e.get("status", ""), e.get("verification", ""))
    await backend.aclose()
    sys.exit(0 if ok else 1)


asyncio.run(main())
