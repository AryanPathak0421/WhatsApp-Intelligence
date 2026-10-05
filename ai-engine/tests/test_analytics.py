from datetime import datetime, timedelta

import pytest

from app.analytics.contribution import compute_contribution
from app.analytics.health import compute_health, status_for
from app.analytics.progress import compute_progress, progress_timeline, velocity
from app.intelligence.pipeline import analyze
from app.intelligence.types import Msg
from app.parsers.whatsapp import WhatsAppParser
from tests.scenario_chat import CHAT

T0 = datetime(2026, 10, 1, 9, 0)


def mk(i, weight, status, domain="DEVELOPMENT", assignee="Amit", deadline=None, done_at=None, ev=(), review=False):
    return {"id": f"t{i}", "title": f"task {i}", "weight": weight, "status": status, "domain": domain,
            "assigned_to": assignee, "deadline": deadline, "completed_at": done_at, "needs_review": review,
            "created_at": T0, "evidence": [{"signal": s, "message_id": "m"} for s in ev],
            "evidence_message_ids": [f"m{i}"]}


# ---------------------------------------------------------------- progress ----
def test_progress_is_weighted_not_counted():
    tasks = [mk(1, 1, "COMPLETED"), mk(2, 1, "COMPLETED"), mk(3, 8, "TODO")]
    p = compute_progress(tasks)
    assert p["overall"] == 20.0  # 2 of 3 tasks done, but only 2/10 of the work


def test_progress_sixty_percent_example():
    weights = [10, 20, 5, 15, 10, 10, 5, 10, 5, 10]
    status = ["COMPLETED", "COMPLETED", "TODO", "COMPLETED", "COMPLETED", "TODO", "COMPLETED", "TODO", "TODO", "TODO"]
    p = compute_progress([mk(i, w, s) for i, (w, s) in enumerate(zip(weights, status))])
    assert p["overall"] == 60.0
    ex = p["explanation"]
    assert ex["completed_weight"] == 60 and ex["total_weight"] == 100
    assert sum(c["points"] for c in ex["task_contributions"]) == 60
    assert all(h["status"] != "COMPLETED" for h in ex["holding_back"])


def test_progress_cancelled_excluded_and_partial_credit_configurable():
    tasks = [mk(1, 4, "COMPLETED"), mk(2, 4, "IN_PROGRESS"), mk(3, 100, "CANCELLED")]
    assert compute_progress(tasks)["overall"] == 50.0
    assert compute_progress(tasks, credits={"IN_PROGRESS": 0.5})["overall"] == 75.0


def test_subprogress_none_means_no_evidence_not_zero():
    p = compute_progress([mk(1, 3, "COMPLETED")])
    assert p["design"] is None and p["deployment"] is None and p["client_approval"] is None


def test_subprogress_domains_testing_deployment_approval():
    tasks = [mk(1, 4, "COMPLETED", ev=["test_pass", "deploy"]), mk(2, 4, "COMPLETED"),
             mk(3, 2, "COMPLETED", domain="DESIGN"), mk(4, 2, "TODO", domain="DESIGN")]
    cp = [{"type": "APPROVAL", "status": "RESOLVED"}, {"type": "UAT", "status": "OPEN"}, {"type": "PAYMENT", "status": "OPEN"}]
    p = compute_progress(tasks, cp)
    assert p["design"] == 50.0 and p["client_approval"] == 50.0
    assert p["testing"] == 50.0       # 4 tested of 8 dev weight
    assert p["deployment"] == round(100 * 4 / 12, 1)


def test_no_tasks_warns():
    p = compute_progress([])
    assert p["overall"] is None and p["explanation"]["warnings"]


def test_timeline_and_velocity():
    tasks = [mk(1, 5, "COMPLETED", done_at=T0 + timedelta(days=1, hours=2)),
             mk(2, 5, "COMPLETED", done_at=T0 + timedelta(days=9)), mk(3, 10, "TODO")]
    tl = progress_timeline(tasks, T0, T0 + timedelta(days=10))
    assert tl[0]["progress"] == 0.0 and tl[1]["progress"] == 25.0 and tl[-1]["progress"] == 50.0
    v = velocity(tasks, T0, T0 + timedelta(days=15))
    assert sum(w["tasks"] for w in v["weeks"]) == 2 and len(v["weeks"]) == 3


# ------------------------------------------------------------------ health ----
RISK = {"score": 20.0, "level": "LOW", "factors": {"client_pending": {"value": 0.0}, "bugs": {"value": 0.0}}}
VEL = {"weeks": [], "trend": None}


def test_health_thresholds():
    assert [status_for(x) for x in (100, 80, 79.9, 60, 59.9, 40, 39.9, 0)] == \
        ["HEALTHY", "HEALTHY", "AT_RISK", "AT_RISK", "CRITICAL", "CRITICAL", "BLOCKED", "BLOCKED"]


def test_health_components_sum_to_score_and_drop_unavailable():
    tasks = [mk(1, 5, "COMPLETED"), mk(2, 5, "TODO")]
    prog = compute_progress(tasks)
    h = compute_health(tasks, prog, RISK, VEL, T0 + timedelta(days=3))
    assert "velocity" in h["unavailable"] and "deadline" in h["unavailable"]
    assert abs(sum(c["contribution"] for c in h["components"].values()) - h["score"]) < 0.2
    assert abs(sum(c["effective_weight"] for c in h["components"].values()) - 1.0) < 0.01


def test_health_uses_timeline_when_delivery_date_known():
    tasks = [mk(1, 5, "COMPLETED"), mk(2, 5, "TODO")]
    prog = compute_progress(tasks)  # 50%
    now = T0 + timedelta(days=5)
    ahead = compute_health(tasks, prog, RISK, VEL, now, T0, T0 + timedelta(days=20))   # 25% elapsed
    behind = compute_health(tasks, prog, RISK, VEL, now, T0, T0 + timedelta(days=6))   # 83% elapsed
    assert ahead["components"]["progress"]["value"] == 1.0
    assert behind["components"]["progress"]["value"] < 0.7 and behind["score"] < ahead["score"]


def test_health_blocked_override_and_configurable_weights():
    tasks = [mk(1, 5, "BLOCKED"), mk(2, 5, "BLOCKED")]
    h = compute_health(tasks, compute_progress(tasks), RISK, VEL, T0)
    assert h["status"] == "BLOCKED" and h["overrides"]
    t2 = [mk(1, 5, "COMPLETED"), mk(2, 5, "TODO")]
    a = compute_health(t2, compute_progress(t2), RISK, VEL, T0)
    b = compute_health(t2, compute_progress(t2), RISK, VEL, T0, weights={"risk": 0.9})
    assert a["score"] != b["score"] and b["components"]["risk"]["effective_weight"] > 0.5


# ------------------------------------------------------------ contribution ----
class M:  # minimal message stub
    def __init__(self, id, sender, text="x"):
        self.id, self.sender, self.text = id, sender, text


def test_message_count_does_not_change_score():
    tasks = [mk(1, 5, "COMPLETED", deadline=T0 + timedelta(days=2), done_at=T0 + timedelta(days=1)), mk(2, 3, "TODO")]
    few = compute_contribution(tasks, [], [], [M("a", "Amit")], {}, T0 + timedelta(days=3))
    many = compute_contribution(tasks, [], [], [M(str(i), "Amit") for i in range(1000)], {}, T0 + timedelta(days=3))
    assert few[0]["score"] == many[0]["score"]
    assert many[0]["info_only"]["message_count"] == 1000


def test_contribution_explainable_and_ordered():
    tasks = [mk(1, 5, "COMPLETED", assignee="Amit", deadline=T0 + timedelta(days=2), done_at=T0 + timedelta(days=1)),
             mk(2, 5, "COMPLETED", assignee="Amit", deadline=T0 + timedelta(days=2), done_at=T0 + timedelta(days=1)),
             mk(3, 5, "COMPLETED", assignee="Amit", deadline=T0 + timedelta(days=2), done_at=T0 + timedelta(days=1)),
             mk(4, 5, "TODO", assignee="Rohan"), mk(5, 5, "TODO", assignee="Rohan"), mk(6, 5, "TODO", assignee="Rohan")]
    out = compute_contribution(tasks, [], [], [], {}, T0 + timedelta(days=3))
    assert [c["person"] for c in out] == ["Amit", "Rohan"]
    a = out[0]
    assert a["score"] == 100.0 and not a["low_sample"] and a["on_time_pct"] == 100.0
    assert abs(sum(c["contribution"] for c in a["components"].values() if "contribution" in c) - a["score"]) < 0.2
    assert out[1]["score"] == 0.0


def test_blocked_is_penalty_only():
    tasks = [mk(i, 5, "COMPLETED") for i in range(3)] + [mk(9, 5, "BLOCKED")]
    base = compute_contribution(tasks[:3] + [mk(9, 5, "TODO")], [], [], [], {}, T0)[0]["score"]
    pen = compute_contribution(tasks, [], [], [], {}, T0)[0]
    assert pen["score"] < base and "blocked_penalty" in pen["components"]


def test_overdue_counted():
    tasks = [mk(1, 3, "IN_PROGRESS", deadline=T0 - timedelta(days=1))]
    assert compute_contribution(tasks, [], [], [], {}, T0)[0]["overdue"] == 1


# ------------------------------------------------------------- integration ----
@pytest.fixture(scope="module")
def result():
    return analyze([Msg.from_parsed(m) for m in WhatsAppParser().parse_text(CHAT)])


def test_scenario_progress_matches_manual_math(result):
    p = result["progress"]
    live = [t for t in result["tasks"] if t["status"] != "CANCELLED"]
    done = sum(t["weight"] for t in live if t["status"] == "COMPLETED")
    assert p["overall"] == round(100 * done / sum(t["weight"] for t in live), 1)
    assert p["explanation"]["task_contributions"] and 0 <= p["explanation"]["reliability"] <= 1


def test_scenario_health_contribution_sales(result):
    h = result["health"]
    assert 0 <= h["score"] <= 100 and h["status"] in ("HEALTHY", "AT_RISK", "CRITICAL", "BLOCKED")
    amit = next(c for c in result["contribution"] if c["person"] == "Amit")
    assert amit["completed"] == 1 and amit["commitments_fulfilled"] == 1
    neha = result["sales"][0]
    assert neha["person"] == "Sales - Neha" and neha["follow_ups_pending"] == 1
    assert result["communication"]["tasks_received"]["Amit"] == 1
