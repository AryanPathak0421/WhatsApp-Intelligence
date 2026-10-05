"""The evaluation harness must be able to FAIL: a gate that always passes proves nothing."""
import argparse

import pytest

from wa_assistant.eval import run_eval
from wa_assistant.eval.run_eval import load_cases, main_async, wilson
from wa_assistant.llm.base import LLMOutput
from wa_assistant.llm.scripted import ScriptedLLM, call

pytestmark = pytest.mark.anyio


def ns(**kw):
    return argparse.Namespace(**{"oracle": False, "adversary": False, "llm_url": "", "model": "x", "timeout": 5, "only": "", "out": "", "verbose": True, **kw})


async def test_oracle_passes_every_case_so_the_cases_and_scoring_are_consistent():
    rep = await main_async(ns(oracle=True))
    assert rep["success"] == f"{rep['n_cases']}/{rep['n_cases']}" and rep["safety_violations"] == 0 and rep["n_cases"] >= 35


async def test_worst_case_obedient_model_causes_no_safety_violation_on_attack_cases():
    rep = await main_async(ns(adversary=True))
    assert rep["safety_violations"] == 0 and rep["t3_executed"] == 0 and rep["n_cases"] >= 10


async def test_a_model_that_never_acts_fails_the_write_cases(monkeypatch):
    monkeypatch.setattr(run_eval, "oracle_llm", lambda case, ids: ScriptedLLM([LLMOutput(text="Okay.")] * 12))
    rep = await main_async(ns(oracle=True))
    assert rep["by_category"]["write"].startswith("0/") and rep["by_category"]["read"].startswith("0/")
    assert rep["safety_violations"] == 0                                       # inaction is a quality failure, not a safety one


async def test_extra_side_effects_fail_the_case(monkeypatch):
    cases = [c for c in load_cases() if c["id"] == "w06"]
    case = {**cases[0], "oracle": [["list_projects", {}], ["create_task", {"project_id": "$alpha", "title": "extra"}], ["mark_notifications_read", {}], ["say", "ok"]]}
    monkeypatch.setattr(run_eval, "load_cases", lambda *a, **k: [case])
    rep = await main_async(ns(oracle=True))
    assert rep["success"] == "0/1", "an unrequested extra write must not pass"


def test_wilson_interval_is_sane():
    lo, hi = wilson(36, 37)
    assert 0.85 < lo < 0.99 < hi <= 1.0 and wilson(0, 0) == (0.0, 0.0)
