import pytest

from wa_assistant.llm.base import LLMOutput
from wa_assistant.llm.scripted import ScriptedLLM, call
from wa_assistant.pending import PendingError

pytestmark = pytest.mark.anyio

ALPHA = "11111111-aaaa-4aaa-8aaa-111111111111"
BETA = "22222222-bbbb-4bbb-8bbb-222222222222"


def T(*calls):
    return LLMOutput(tool_calls=list(calls))


def say(text):
    return LLMOutput(text=text)


async def test_read_flow_uses_live_data_and_labels_the_source(make_env):
    env = make_env(ScriptedLLM([T(call("list_projects")), say("You have one project: Alpha.")]))
    r = await env.say(env.session("pm"), "which projects do I have?")
    assert "Alpha" in r.reply and "application_data" in r.sources and not r.pending
    assert env.world.snapshot()["tasks"] == env.world.snapshot()["tasks"]


async def test_t1_write_is_executed_verified_and_changes_exactly_what_was_asked(make_env):
    env = make_env(ScriptedLLM([T(call("list_projects")), T(call("create_task", project_id=ALPHA, title="Write release notes", priority="HIGH")),
                                say("Task created.")]))
    before = env.world.snapshot()
    r = await env.say(env.session("pm"), "add a task Write release notes, high priority, in Alpha")
    after = env.world.snapshot()
    assert r.actions[-1]["status"] == "verified"
    new = {k: v for k, v in after["tasks"].items() if k not in before["tasks"]}
    assert len(new) == 1 and next(iter(new.values()))["title"] == "Write release notes" and next(iter(new.values()))["priority"] == "HIGH"
    assert {k: v for k, v in after.items() if k != "tasks"} == {k: v for k, v in before.items() if k != "tasks"}
    assert "Done and verified" in r.reply


async def test_invented_ids_are_rejected_before_any_call_is_made(make_env):
    env = make_env(ScriptedLLM([T(call("create_task", project_id=BETA, title="x")), say("I need to look up your projects first.")]))
    before = env.world.snapshot()
    r = await env.say(env.session("pm"), "create a task in Beta")
    assert env.world.snapshot() == before and not r.actions
    assert any(m["role"] == "tool" and "was not returned by any earlier lookup" in m["content"] for m in env.a.agent.llm.calls[1]["messages"])


async def test_invalid_arguments_are_reported_to_the_model_and_never_executed(make_env):
    env = make_env(ScriptedLLM([T(call("list_projects")), T(call("create_task", project_id=ALPHA, title="x", priority="URGENT-ish", color="red")),
                                say("Which priority do you want?")]))
    before = env.world.snapshot()
    await env.say(env.session("pm"), "add task x")
    assert env.world.snapshot() == before


async def test_t2_needs_confirmation_executes_once_and_only_for_its_owner(make_env):
    env = make_env(ScriptedLLM([T(call("list_projects")), T(call("list_tasks", project_id=ALPHA)),
                                T(call("complete_task", task_id="__LOGIN__")), say("Please confirm.")]))
    s = env.session("pm")
    # the scripted model needs the real task id returned by the listing
    env.a.agent.llm.outputs[2] = T(call("complete_task", task_id=env.ids["t_login"]))
    r = await env.say(s, "mark the login task as done")
    assert r.pending and r.pending[0]["tool"] == "complete_task"
    assert env.world.tasks[env.ids["t_login"]]["status"] == "TODO"                       # nothing happened yet
    pid = r.pending[0]["id"]
    other = env.session("admin")
    assert (await env.a.agent.confirm(other, pid)).actions[0]["status"] == "refused"      # not your action
    done = await env.a.agent.confirm(s, pid)
    assert done.actions[0]["status"] == "verified" and env.world.tasks[env.ids["t_login"]]["status"] == "COMPLETED"
    again = await env.a.agent.confirm(s, pid)                                             # single use
    assert again.actions[0]["status"] == "refused"


async def test_cancelling_a_pending_action_changes_nothing(make_env):
    env = make_env(ScriptedLLM([T(call("list_projects")), T(call("list_tasks", project_id=ALPHA)), say("x")]))
    s = env.session("pm")
    env.a.agent.llm.outputs.insert(2, T(call("cancel_task", task_id=env.ids["t_invoice"])))
    r = await env.say(s, "cancel the invoice task")
    before = env.world.snapshot()
    c = env.a.agent.cancel(s, r.pending[0]["id"])
    assert "Cancelled" in c.reply and env.world.snapshot() == before
    assert (await env.a.agent.confirm(s, r.pending[0]["id"])).actions[0]["status"] == "refused"


async def test_t3_actions_are_refused_even_with_a_known_id(make_env):
    env = make_env(ScriptedLLM([T(call("list_projects")), T(call("list_tasks", project_id=ALPHA)),
                                T(call("delete_task", task_id="x")), say("I can't delete tasks from chat.")]))
    s = env.session("pm")
    env.a.agent.llm.outputs[2] = T(call("delete_task", task_id=env.ids["t_login"]))
    before = env.world.snapshot()
    r = await env.say(s, "delete the login task")
    assert any(a["status"] == "refused" and "admin interface" in a["reason"] for a in r.actions) and env.world.snapshot() == before


async def test_backend_permissions_apply_to_the_assistant_as_to_the_user(make_env):
    env = make_env(ScriptedLLM([T(call("list_projects")), T(call("create_task", project_id=ALPHA, title="sneaky")), say("ok")]))
    before = env.world.snapshot()
    r = await env.say(env.session("viewer"), "add a task sneaky")
    assert r.actions[-1]["status"] == "failed" and "permission" in r.actions[-1]["error"] and env.world.snapshot() == before


async def test_spoofed_project_id_from_the_screen_cannot_reach_an_inaccessible_project(make_env):
    env = make_env(ScriptedLLM([T(call("get_progress", project_id=BETA)), say("done")]))
    r = await env.say(env.session("pm"), "show progress", app_state={"page": "project", "project_id": BETA})
    assert r.actions[0]["status"] == "failed" and "not found" in r.actions[0]["error"]      # the backend answered 404 for the PM


async def test_team_member_may_change_status_but_not_other_fields(make_env):
    env = make_env(ScriptedLLM([T(call("list_projects")), T(call("list_tasks", project_id=ALPHA)), say("x")]))
    s = env.session("member")
    env.a.agent.llm.outputs.insert(2, T(call("update_task", task_id=env.ids["t_login"], title="Renamed")))
    r = await env.say(s, "rename the login task")
    assert r.pending                                                   # follows a task listing (chat-derived text), so it asks first
    done = await env.a.agent.confirm(s, r.pending[0]["id"])
    assert done.actions[0]["status"] == "failed" and env.world.tasks[env.ids["t_login"]]["title"] == "Build login page"   # backend says 403


async def test_a_claim_of_success_without_an_executed_action_is_flagged(make_env):
    env = make_env(ScriptedLLM([say("I've created the task for you.")]))
    r = await env.say(env.session("pm"), "create a task")
    assert "no change was made" in r.reply.lower() and r.issues


async def test_write_rate_limit(make_env):
    outs = [T(call("list_projects"))] + [T(call("create_task", project_id=ALPHA, title=f"t{i}")) for i in range(4)] + [say("done")]
    env = make_env(ScriptedLLM(outs), writes_per_minute=2)
    r = await env.say(env.session("pm"), "create many tasks")
    assert sum(1 for a in r.actions if a["status"] == "verified") == 2 and any(a["status"] == "refused" for a in r.actions)


async def test_audit_records_decisions_without_message_text(make_env):
    env = make_env(ScriptedLLM([T(call("list_projects")), say("ok")]))
    await env.say(env.session("pm"), "my secret client name is ACME-CONFIDENTIAL")
    log = env.a.audit.read()
    assert {"user_message", "tool_decision", "read_result", "turn_end"} <= {e["event"] for e in log}
    assert "ACME-CONFIDENTIAL" not in open(env.a.audit.path, encoding="utf-8").read()


async def test_sessions_cannot_be_hijacked_by_another_user(make_env):
    env = make_env(ScriptedLLM([]))
    s = env.session("pm")
    other = env.world.users[env.ids["admin"]]
    s2 = env.a.sessions.get_or_create(s.id, other["id"], other["role"], env.ids["tok_admin"])
    assert s2.id != s.id
