"""A TINY RULE-BASED STAND-IN for the language model, for checking the UI and the confirmation flow end to end when no real model is installed.

It is NOT an LLM and says so in its fallback reply. It understands three phrasings only: "list projects", "list tasks [in <project>]",
"complete <task words>". Everything else (policy, verification, permissions, audit) is the real assistant code talking to the real backend.

    python scripts/mock_llm_server.py --port 8080
"""
import argparse
import json
import re
import uuid

import uvicorn
from fastapi import FastAPI, Request

app = FastAPI()


def tool_json(content: str):
    try:
        d = json.loads(content)
    except ValueError:
        return {}
    data = d.get("data")
    if isinstance(data, str):
        try:
            data = json.loads(data.removeprefix("<untrusted_data>").removesuffix("</untrusted_data>"))
        except ValueError:
            data = None
    return {"ok": d.get("ok"), "data": data, "status": d.get("status")}


def call(name, **args):
    return {"role": "assistant", "content": None, "tool_calls": [{"id": f"call_{uuid.uuid4().hex[:8]}", "type": "function",
                                                                  "function": {"name": name, "arguments": json.dumps(args)}}]}


def respond(messages):
    last_user = max((i for i, m in enumerate(messages) if m["role"] == "user"), default=-1)
    user = (messages[last_user]["content"] or "").lower()
    since = messages[last_user + 1:]
    called = [tc["function"]["name"] for m in since if m.get("tool_calls") for tc in m["tool_calls"]]
    results = {}
    for m, nxt in zip(since, since[1:] + [None]):
        if m.get("tool_calls") and nxt and nxt["role"] == "tool":
            results[m["tool_calls"][0]["function"]["name"]] = tool_json(nxt["content"])
    projects = ((results.get("list_projects") or {}).get("data") or {}).get("items", [])
    tasks = ((results.get("list_tasks") or {}).get("data") or {}).get("items", [])
    if "awaiting_user_confirmation" in json.dumps([m.get("content") for m in since if m["role"] == "tool"]):
        return {"role": "assistant", "content": "I have prepared that change; please confirm it with the button."}
    if re.search(r"\bprojects?\b", user) and not re.search(r"task|complete|done", user):
        if "list_projects" not in called:
            return call("list_projects")
        return {"role": "assistant", "content": "Your projects: " + (", ".join(p["name"] for p in projects) or "none") + "."}
    if re.search(r"\btasks?\b|complete|done", user):
        if "list_projects" not in called:
            return call("list_projects")
        pick = next((p for p in projects if p["name"].lower() in user), projects[0] if projects else None)
        if not pick:
            return {"role": "assistant", "content": "I could not find a project."}
        if "list_tasks" not in called:
            return call("list_tasks", project_id=pick["id"])
        if re.search(r"complete|done", user):
            words = set(re.findall(r"[a-z]{3,}", user)) - {"complete", "mark", "the", "task", "done", "please", "alpha"}
            t = next((t for t in tasks if words & set(re.findall(r"[a-z]{3,}", t["title"].lower())) and t["status"] != "COMPLETED"), None)
            if not t:
                return {"role": "assistant", "content": "Which task do you mean? I could not match it."}
            return call("complete_task", task_id=t["id"])
        return {"role": "assistant", "content": "Tasks: " + "; ".join(f"{t['title']} ({t['status']})" for t in tasks) + "."}
    return {"role": "assistant", "content": "I am a rule-based stand-in for the UI check, not a language model. Try: 'list projects', 'list tasks', 'complete <task>'."}


@app.get("/v1/models")
def models():
    return {"data": [{"id": "mock-rules"}]}


@app.post("/v1/chat/completions")
async def completions(request: Request):
    body = await request.json()
    return {"choices": [{"message": respond(body["messages"])}], "usage": {}}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    uvicorn.run(app, host="127.0.0.1", port=ap.parse_args().port)
