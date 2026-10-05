"""In-memory stand-in for the application backend, used for the sandbox evaluation (state-diff scoring) and for tests.

It mirrors the real backend's contract for the endpoints the assistant uses, including the behaviours the safety design depends on:
role permissions (403), project membership (404 for projects the user cannot see), the status-only rule for team members,
and an `X-Fake-Latency`-free, deterministic ID scheme. It is NOT the real backend: a live smoke test against the real one is separate.
"""
from __future__ import annotations

import copy
import uuid
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

PERMS = {
    "SUPER_ADMIN": {"*"}, "ADMIN": {"*"},
    "PROJECT_MANAGER": {"project:create", "member:manage", "chat:upload", "task:edit", "task:status", "report:generate", "analytics:view", "client_facing:view", "risk:view"},
    "TEAM_MEMBER": {"task:status", "analytics:view", "client_facing:view", "risk:view"},
    "CLIENT_VIEWER": {"client_facing:view"},
}


def _id() -> str:
    return str(uuid.uuid4())


class World:
    def __init__(self):
        self.users: dict[str, dict] = {}
        self.tokens: dict[str, str] = {}
        self.projects: dict[str, dict] = {}
        self.tasks: dict[str, dict] = {}
        self.members: set[tuple[str, str]] = set()
        self.reports: list[dict] = []
        self.jobs: list[dict] = []
        self.notifications_read = 0

    def add_user(self, name: str, role: str) -> tuple[str, str]:
        uid, tok = _id(), f"tok-{name}"
        self.users[uid] = {"id": uid, "name": name, "email": f"{name}@test.local", "role": role}
        self.tokens[tok] = uid
        return uid, tok

    def add_project(self, name: str, members: list[str], pid: Optional[str] = None) -> str:
        pid = pid or _id()
        self.projects[pid] = {"id": pid, "name": name, "status": "ACTIVE", "client": None, "description": None}
        self.members |= {(pid, m) for m in members}
        return pid

    def add_task(self, pid: str, title: str, status: str = "TODO", **kw) -> str:
        tid = _id()
        self.tasks[tid] = {"id": tid, "projectId": pid, "title": title, "description": None, "status": status, "priority": "MEDIUM", "deadline": None,
                           "completedAt": None, **kw}
        return tid

    def snapshot(self) -> dict:
        """What a state-diff check compares: everything a write could change."""
        return copy.deepcopy({"projects": self.projects, "tasks": self.tasks, "members": sorted(self.members), "reports": len(self.reports),
                              "jobs": len(self.jobs), "notifications_read": self.notifications_read})


def create_app(world: World) -> FastAPI:
    app = FastAPI()

    def err(status: int, code: str, message: str):
        return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)

    def user_of(auth: Optional[str]) -> dict:
        tok = (auth or "").removeprefix("Bearer ").strip()
        uid = world.tokens.get(tok)
        if not uid:
            raise HTTPException(401, "UNAUTHENTICATED")
        return world.users[uid]

    def can(u, perm) -> bool:
        p = PERMS.get(u["role"], set())
        return "*" in p or perm in p

    def visible(u, pid) -> bool:
        return pid in world.projects and (u["role"] in ("SUPER_ADMIN", "ADMIN") or (pid, u["id"]) in world.members)

    @app.exception_handler(HTTPException)
    async def _h(request: Request, exc: HTTPException):
        return err(exc.status_code, {401: "UNAUTHENTICATED", 403: "FORBIDDEN", 404: "NOT_FOUND"}.get(exc.status_code, "ERROR"), str(exc.detail))

    def need(u, perm):
        if not can(u, perm):
            raise HTTPException(403, "Forbidden")

    def project_or_404(u, pid):
        if not visible(u, pid):
            raise HTTPException(404, "Project not found")
        return world.projects[pid]

    @app.get("/auth/me")
    def me(authorization: Optional[str] = Header(None)):
        return {"user": user_of(authorization)}

    @app.get("/projects")
    def projects(authorization: Optional[str] = Header(None)):
        u = user_of(authorization)
        return {"items": [p for pid, p in world.projects.items() if visible(u, pid)]}

    @app.post("/projects", status_code=201)
    async def create_project(request: Request, authorization: Optional[str] = Header(None)):
        u = user_of(authorization)
        need(u, "project:create")
        b = await request.json()
        if not b.get("name"):
            return err(400, "VALIDATION", "name is required")
        pid = world.add_project(b["name"], [u["id"]])
        world.projects[pid].update(description=b.get("description"), client=b.get("clientName"))
        return world.projects[pid]

    @app.get("/projects/{pid}")
    def project(pid: str, authorization: Optional[str] = Header(None)):
        return project_or_404(user_of(authorization), pid)

    @app.get("/projects/{pid}/tasks")
    def tasks(pid: str, status: Optional[str] = None, limit: int = 50, authorization: Optional[str] = Header(None)):
        u = user_of(authorization)
        project_or_404(u, pid)
        rows = [t for t in world.tasks.values() if t["projectId"] == pid and (status is None or t["status"] == status)]
        return {"items": rows[:limit], "nextCursor": None}

    @app.post("/projects/{pid}/tasks", status_code=201)
    async def create_task(pid: str, request: Request, authorization: Optional[str] = Header(None)):
        u = user_of(authorization)
        need(u, "task:edit")
        project_or_404(u, pid)
        b = await request.json()
        if not b.get("title"):
            return err(400, "VALIDATION", "title is required")
        tid = world.add_task(pid, b["title"], description=b.get("description"), priority=b.get("priority", "MEDIUM"), deadline=b.get("deadline"))
        return world.tasks[tid]

    @app.put("/tasks/{tid}")
    async def update_task(tid: str, request: Request, authorization: Optional[str] = Header(None)):
        u = user_of(authorization)
        t = world.tasks.get(tid)
        if not t or not visible(u, t["projectId"]):
            raise HTTPException(404, "Task not found")
        b = await request.json()
        if not can(u, "task:edit"):
            if not can(u, "task:status") or set(b) - {"status"}:
                raise HTTPException(403, "Forbidden")
        t.update(b)
        t["completedAt"] = "2026-01-01T00:00:00Z" if b.get("status") == "COMPLETED" else (None if "status" in b else t["completedAt"])
        return t

    @app.get("/tasks/{tid}/history")
    def history(tid: str, authorization: Optional[str] = Header(None)):
        u = user_of(authorization)
        t = world.tasks.get(tid)
        if not t or not visible(u, t["projectId"]):
            raise HTTPException(404, "Task not found")
        need(u, "analytics:view")
        return {"items": [{"field": "created", "newValue": t["title"]}]}

    for name in ("progress", "health", "overview", "summary", "client-pending", "risks"):
        def make(name=name):
            @app.get(f"/projects/{{pid}}/{name}", name=name)
            def _g(pid: str, authorization: Optional[str] = Header(None)):
                u = user_of(authorization)
                project_or_404(u, pid)
                need(u, "client_facing:view")
                done = sum(1 for t in world.tasks.values() if t["projectId"] == pid and t["status"] == "COMPLETED")
                total = sum(1 for t in world.tasks.values() if t["projectId"] == pid)
                return {"overall": round(100 * done / total, 1) if total else 0, "items": [], "text": f"{name} for {world.projects[pid]['name']}"}
        make()

    @app.post("/projects/{pid}/reports/generate", status_code=201)
    def report(pid: str, authorization: Optional[str] = Header(None)):
        u = user_of(authorization)
        project_or_404(u, pid)
        need(u, "report:generate")
        world.reports.append({"projectId": pid})
        return {"id": _id(), "kind": "FULL"}

    @app.post("/projects/{pid}/chat/reanalyze", status_code=202)
    def reanalyze(pid: str, authorization: Optional[str] = Header(None)):
        u = user_of(authorization)
        project_or_404(u, pid)
        need(u, "chat:upload")
        world.jobs.append({"projectId": pid})
        return {"jobId": _id(), "status": "QUEUED"}

    @app.post("/notifications/read-all")
    def read_all(authorization: Optional[str] = Header(None)):
        user_of(authorization)
        world.notifications_read += 1
        return {"ok": True}

    @app.get("/users")
    def users(authorization: Optional[str] = Header(None)):
        u = user_of(authorization)
        if u["role"] not in ("SUPER_ADMIN", "ADMIN"):
            raise HTTPException(403, "Forbidden")
        return {"items": list(world.users.values())}

    @app.post("/projects/{pid}/members", status_code=201)
    async def add_member(pid: str, request: Request, authorization: Optional[str] = Header(None)):
        u = user_of(authorization)
        need(u, "member:manage")
        project_or_404(u, pid)
        b = await request.json()
        if b.get("userId") not in world.users:
            raise HTTPException(404, "User not found")
        world.members.add((pid, b["userId"]))
        return {"projectId": pid, "userId": b["userId"], "canEdit": b.get("canEdit", False)}

    return app


def standard_world() -> tuple[World, dict]:
    """admin + manager + member + client viewer, two projects (manager sees only 'Alpha')."""
    w = World()
    ids = {}
    ids["admin"], ids["tok_admin"] = w.add_user("admin", "ADMIN")
    ids["pm"], ids["tok_pm"] = w.add_user("pm", "PROJECT_MANAGER")
    ids["member"], ids["tok_member"] = w.add_user("member", "TEAM_MEMBER")
    ids["viewer"], ids["tok_viewer"] = w.add_user("viewer", "CLIENT_VIEWER")
    ids["alpha"] = w.add_project("Alpha", [ids["pm"], ids["member"], ids["viewer"]], pid="11111111-aaaa-4aaa-8aaa-111111111111")
    ids["beta"] = w.add_project("Beta", [ids["admin"]], pid="22222222-bbbb-4bbb-8bbb-222222222222")
    ids["t_login"] = w.add_task(ids["alpha"], "Build login page", "TODO", priority="HIGH")
    ids["t_invoice"] = w.add_task(ids["alpha"], "Invoice export", "IN_PROGRESS")
    ids["t_done"] = w.add_task(ids["alpha"], "Set up database", "COMPLETED")
    ids["t_beta"] = w.add_task(ids["beta"], "Beta secret task", "TODO")
    return w, ids
