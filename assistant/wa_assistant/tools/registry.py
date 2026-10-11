"""Tool registry: the ONLY actions the assistant can take. Each tool = typed arguments + risk tier + the backend endpoint it maps to.

Tiers   T0 read-only | T1 reversible write | T2 sensitive (explicit UI confirmation) | T3 never available through chat (refused, user is
        pointed to the admin UI). T3 tools are registered without an endpoint so a model asking for them gets a clear refusal, not "unknown tool".
Rules   arguments are validated by the pydantic model (extra fields rejected); ids (project/task/user) must have been returned by an earlier read
        in the same session, so a model cannot invent or guess one; tools that return chat/document text are flagged `untrusted`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

NO_ID = ""


class Tier(str, Enum):
    T0 = "T0"
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class NoArgs(Args):
    pass


class ProjectRef(Args):
    project_id: str = Field(min_length=8, max_length=64, description="Project id returned by list_projects.")


class TaskRef(Args):
    task_id: str = Field(min_length=8, max_length=64, description="Task id returned by list_tasks.")


class ListTasksArgs(ProjectRef):
    status: Optional[Literal["TODO", "IN_PROGRESS", "COMPLETED", "BLOCKED", "CANCELLED"]] = None
    overdue: Optional[bool] = None
    needs_review: Optional[bool] = None
    limit: int = Field(50, ge=1, le=100)


class CreateProjectArgs(Args):
    name: str = Field(min_length=1, max_length=150)
    description: Optional[str] = Field(None, max_length=2000)
    client_name: Optional[str] = Field(None, max_length=150)


_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class CreateTaskArgs(ProjectRef):
    title: str = Field(min_length=1, max_length=300)
    description: Optional[str] = Field(None, max_length=4000)
    priority: Optional[Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]] = None
    deadline: Optional[str] = Field(None, description="ISO date YYYY-MM-DD.")

    @field_validator("deadline")
    @classmethod
    def _d(cls, v):
        if v is not None and not _DATE.match(v):
            raise ValueError("deadline must be YYYY-MM-DD")
        return v


class UpdateTaskArgs(TaskRef):
    title: Optional[str] = Field(None, min_length=1, max_length=300)
    description: Optional[str] = Field(None, max_length=4000)
    priority: Optional[Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]] = None
    deadline: Optional[str] = Field(None, description="ISO date YYYY-MM-DD.")

    @field_validator("deadline")
    @classmethod
    def _d(cls, v):
        if v is not None and not _DATE.match(v):
            raise ValueError("deadline must be YYYY-MM-DD")
        return v

    @model_validator(mode="after")
    def _some(self):
        if not any(getattr(self, k) is not None for k in ("title", "description", "priority", "deadline")):
            raise ValueError("give at least one field to change")
        return self


class GenerateReportArgs(ProjectRef):
    kind: Literal["FULL", "DAILY", "WEEKLY"] = "FULL"


class AddMemberArgs(ProjectRef):
    user_id: str = Field(min_length=8, max_length=64, description="User id returned by list_users.")
    can_edit: bool = False


class SearchDocsArgs(Args):
    query: str = Field(min_length=2, max_length=500)
    project_id: Optional[str] = Field(None, max_length=64, description="Limit to one project's documents; omit for the shared paper library.")
    year_min: Optional[int] = Field(None, ge=1900, le=2100)
    tag: Optional[str] = Field(None, max_length=60)
    k: int = Field(5, ge=1, le=8)


PAGES = ("dashboard", "projects", "project", "tasks", "risks", "reports", "analytics", "team", "timeline", "client_pending", "settings")


class NavigateArgs(Args):
    page: Literal[PAGES]                                                        # type: ignore[valid-type]
    project_id: Optional[str] = Field(None, max_length=64)


class SetFilterArgs(Args):
    days: Optional[int] = Field(None, ge=1, le=365)
    status: Optional[Literal["TODO", "IN_PROGRESS", "COMPLETED", "BLOCKED", "CANCELLED"]] = None

    @model_validator(mode="after")
    def _some(self):
        if self.days is None and self.status is None:
            raise ValueError("give days and/or status")
        return self


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: type[Args]
    tier: Tier
    method: str = ""
    path: str = ""                                          # "/projects/{project_id}/tasks"
    query: tuple = ()                                       # arg names sent as query string
    body: dict = field(default_factory=dict)                # arg name -> body key (empty + write method => all non-path args)
    fixed_body: dict = field(default_factory=dict)          # constant body fields (e.g. status=COMPLETED)
    id_args: dict = field(default_factory=dict)             # arg name -> id kind that must have been seen earlier
    learns: Optional[Callable[[Any, dict], list]] = None    # (response data, args) -> [(kind, id[, parent_project])]
    untrusted: bool = False                                 # result carries chat/document text
    local: str = ""                                         # "ui_event" | "documents": handled without the backend
    preview: Optional[Callable[[dict], str]] = None
    verify: Optional[Callable[..., Awaitable[tuple]]] = None
    refusal: str = ""                                       # T3 message

    def llm_schema(self) -> dict:
        """Compact schema for the model: every prompt token costs ~50 ms on CPU. Validation stays in the pydantic model (limits, extra=forbid)."""
        sch = self.args.model_json_schema()
        props = {}
        for k, p in sch.get("properties", {}).items():
            p = {a: b for a, b in p.items() if a in ("type", "enum", "description", "items", "anyOf", "format")}
            if "anyOf" in p:                                                   # Optional[X] -> X
                real = [x for x in p.pop("anyOf") if x.get("type") != "null"]
                if len(real) == 1:
                    p.update({a: b for a, b in real[0].items() if a in ("type", "enum", "items", "format")})
            if p.get("description", "").startswith("Project id returned by"):
                p["description"] = "from list_projects"
            props[k] = p
        out = {"type": "object", "properties": props}
        if sch.get("required"):
            out["required"] = sch["required"]
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": out}}


# ---- verification (independent read-back wherever the backend offers one) ----

async def _verify_project(client, token, args, data, session):
    pid = (data or {}).get("id")
    r = await client.request("GET", f"/projects/{pid}", token)
    if not r.ok:
        return False, "the project could not be read back"
    return (r.data or {}).get("name") == args["name"], "project read back with the requested name"


async def _read_task(client, token, session, task_id):
    pid = session.task_project.get(task_id)
    if not pid:
        return None
    r = await client.request("GET", f"/projects/{pid}/tasks", token, params={"limit": 100})
    if not r.ok:
        return None
    return next((t for t in (r.data or {}).get("items", []) if t.get("id") == task_id), None)


async def _verify_task_fields(client, token, args, data, session, expect: dict):
    row = await _read_task(client, token, session, args.get("task_id") or (data or {}).get("id"))
    source = "read back from the task list" if row is not None else "taken from the write response (no independent read-back available)"
    row = row if row is not None else (data or {})
    bad = [k for k, v in expect.items() if k != "deadline" and row.get(k) != v]
    if "deadline" in expect and str(row.get("deadline") or "")[:10] != expect["deadline"]:
        bad.append("deadline")
    return (not bad), (source if not bad else f"mismatch in {', '.join(bad)}")


def _expect_from(args: dict, keys=("title", "description", "priority", "deadline")) -> dict:
    return {k: args[k] for k in keys if args.get(k) is not None}


def _learn_items(kind):
    def f(data, args):
        items = (data or {}).get("items", data if isinstance(data, list) else [])
        pid = args.get("project_id")
        return [(kind, x["id"], pid if kind == "task" else None) for x in items if isinstance(x, dict) and x.get("id")]
    return f


def _learn_one(kind):
    def f(data, args):
        return [(kind, data["id"], args.get("project_id") if kind == "task" else None)] if isinstance(data, dict) and data.get("id") else []
    return f


def _t3(name, what):
    return Tool(name, f"{what} (not available through chat).", NoArgs, Tier.T3,
                refusal=f"I can't do that through chat: {what} must be done by a person in the admin interface, where you can see exactly what will change.")


def build_registry() -> dict[str, Tool]:
    tools = [
        Tool("list_projects", "List the projects the current user can access.", NoArgs, Tier.T0, "GET", "/projects", learns=_learn_items("project")),
        Tool("get_project_overview", "Overview of one project (status, counts).", ProjectRef, Tier.T0, "GET", "/projects/{project_id}/overview",
             id_args={"project_id": "project"}),
        Tool("get_progress", "Progress percentages for a project.", ProjectRef, Tier.T0, "GET", "/projects/{project_id}/progress", id_args={"project_id": "project"}),
        Tool("get_health", "Health score and its components for a project.", ProjectRef, Tier.T0, "GET", "/projects/{project_id}/health", id_args={"project_id": "project"}),
        Tool("get_summary", "Evidence-based text summary of a project.", ProjectRef, Tier.T0, "GET", "/projects/{project_id}/summary",
             id_args={"project_id": "project"}, untrusted=True),
        Tool("list_tasks", "List tasks of a project, optionally filtered by status, overdue or needs_review.", ListTasksArgs, Tier.T0, "GET",
             "/projects/{project_id}/tasks", query=("status", "overdue", "needs_review", "limit"), id_args={"project_id": "project"},
             learns=_learn_items("task"), untrusted=True),
        Tool("get_task_history", "Change history of one task.", TaskRef, Tier.T0, "GET", "/tasks/{task_id}/history", id_args={"task_id": "task"}, untrusted=True),
        Tool("list_client_pending", "Things the client still owes the team in a project.", ProjectRef, Tier.T0, "GET",
             "/projects/{project_id}/client-pending", id_args={"project_id": "project"}, untrusted=True),
        Tool("list_risks", "Risks detected in a project.", ProjectRef, Tier.T0, "GET", "/projects/{project_id}/risks", id_args={"project_id": "project"}, untrusted=True),
        Tool("list_users", "List application users (admins only).", NoArgs, Tier.T0, "GET", "/users", learns=_learn_items("user")),
        Tool("search_documents", "Search ingested research papers and project documents. Returns cited passages; use them to answer and cite as [C1], [C2].",
             SearchDocsArgs, Tier.T0, local="documents", untrusted=True, id_args={}),
        Tool("navigate", "Open a page of the application for the user.", NavigateArgs, Tier.T0, local="ui_event"),
        Tool("set_dashboard_filter", "Change the dashboard filter (time range in days and/or task status).", SetFilterArgs, Tier.T0, local="ui_event"),
        # --- T1: reversible writes (the user can edit or undo them in the UI) ---
        Tool("create_project", "Create a new project.", CreateProjectArgs, Tier.T1, "POST", "/projects",
             body={"name": "name", "description": "description", "client_name": "clientName"}, learns=_learn_one("project"),
             preview=lambda a: f"Create project \"{a['name']}\"", verify=_verify_project),
        Tool("create_task", "Create a task in a project.", CreateTaskArgs, Tier.T1, "POST", "/projects/{project_id}/tasks",
             body={"title": "title", "description": "description", "priority": "priority", "deadline": "deadline"}, id_args={"project_id": "project"},
             learns=_learn_one("task"), preview=lambda a: f"Create task \"{a['title']}\"",
             verify=lambda c, t, a, d, s: _verify_task_fields(c, t, a, d, s, {"title": a["title"], **_expect_from(a, ("priority", "deadline"))})),
        Tool("update_task", "Change a task's title, description, priority or deadline (not its status).", UpdateTaskArgs, Tier.T1, "PUT", "/tasks/{task_id}",
             body={"title": "title", "description": "description", "priority": "priority", "deadline": "deadline"}, id_args={"task_id": "task"},
             preview=lambda a: "Update task: " + ", ".join(f"{k}={a[k]!r}" for k in ("title", "description", "priority", "deadline") if a.get(k) is not None),
             verify=lambda c, t, a, d, s: _verify_task_fields(c, t, a, d, s, _expect_from(a))),
        Tool("generate_report", "Generate a project report (FULL, DAILY or WEEKLY).", GenerateReportArgs, Tier.T1, "POST", "/projects/{project_id}/reports/generate",
             body={"kind": "kind"}, id_args={"project_id": "project"}, preview=lambda a: f"Generate a {a['kind']} report"),
        Tool("reanalyze_project", "Re-run the chat analysis for a project.", ProjectRef, Tier.T1, "POST", "/projects/{project_id}/chat/reanalyze",
             id_args={"project_id": "project"}, preview=lambda a: "Re-run the project analysis"),
        Tool("mark_notifications_read", "Mark all of the user's notifications as read.", NoArgs, Tier.T1, "POST", "/notifications/read-all",
             preview=lambda a: "Mark all notifications as read"),
        # --- T2: sensitive; explicit confirmation in the UI ---
        Tool("complete_task", "Mark a task COMPLETED (changes progress and health figures).", TaskRef, Tier.T2, "PUT", "/tasks/{task_id}",
             fixed_body={"status": "COMPLETED"}, id_args={"task_id": "task"}, preview=lambda a: "Mark the task as COMPLETED (progress and health will change)",
             verify=lambda c, t, a, d, s: _verify_task_fields(c, t, a, d, s, {"status": "COMPLETED"})),
        Tool("cancel_task", "Mark a task CANCELLED.", TaskRef, Tier.T2, "PUT", "/tasks/{task_id}", fixed_body={"status": "CANCELLED"},
             id_args={"task_id": "task"}, preview=lambda a: "Mark the task as CANCELLED",
             verify=lambda c, t, a, d, s: _verify_task_fields(c, t, a, d, s, {"status": "CANCELLED"})),
        Tool("add_project_member", "Give a user access to a project.", AddMemberArgs, Tier.T2, "POST", "/projects/{project_id}/members",
             body={"user_id": "userId", "can_edit": "canEdit"}, id_args={"project_id": "project", "user_id": "user"},
             preview=lambda a: f"Give the user access to the project ({'can edit' if a.get('can_edit') else 'view only'})"),
        # --- T3: refused in chat ---
        _t3("delete_task", "deleting a task"), _t3("delete_project", "deleting a project"), _t3("remove_project_member", "removing a project member"),
        _t3("create_user", "creating a user account"), _t3("change_user_role", "changing a user's role or permissions"),
        _t3("make_payment", "making a payment"), _t3("send_external_message", "sending an email or message outside the application"),
        _t3("export_all_data", "exporting data out of the application"),
    ]
    return {t.name: t for t in tools}
