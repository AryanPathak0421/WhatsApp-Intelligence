import json

import pytest

from app.classifiers.baseline import MessageClassifier, build
from app.monitoring.drift import PredictionLogger, check_drift, psi, summarize
from app.training.registry import GateError, ModelRegistry, main as registry_cli, production_path


def metrics_file(tmp_path, name, real=None, syn=1.0):
    m = {"SYNTHETIC_ONLY_val": {"n": 100, "accuracy": syn, "macro_f1": syn}}
    if real is not None:
        m["REAL_TEST"] = {"n": 300, "accuracy": real, "macro_f1": real, "weighted_f1": real}
    p = tmp_path / f"{name}.metrics.json"
    p.write_text(json.dumps(m))
    return str(p)


@pytest.fixture
def reg(tmp_path):
    return ModelRegistry(tmp_path / "registry")


def test_synthetic_only_model_cannot_be_promoted(reg, tmp_path):
    reg.register("classifier", "v1", "m/v1.joblib", metrics_file(tmp_path, "v1", real=None, syn=1.0))
    with pytest.raises(GateError, match="no REAL_TEST"):
        reg.promote("classifier", "v1", by="alice")
    assert reg.production("classifier") is None


def test_promotion_requires_non_regression_and_floor(reg, tmp_path):
    reg.register("classifier", "v1", "m/v1.joblib", metrics_file(tmp_path, "v1", real=0.70))
    reg.register("classifier", "v2", "m/v2.joblib", metrics_file(tmp_path, "v2", real=0.65))
    reg.register("classifier", "v3", "m/v3.joblib", metrics_file(tmp_path, "v3", real=0.78))
    with pytest.raises(GateError, match="required"):
        reg.promote("classifier", "v1", by="a", min_macro_f1=0.75)
    reg.promote("classifier", "v1", by="a", min_macro_f1=0.6)
    with pytest.raises(GateError, match="below production"):
        reg.promote("classifier", "v2", by="a")
    reg.promote("classifier", "v3", by="a")
    assert reg.production("classifier")["version"] == "v3"
    assert reg.get("classifier", "v1")["stage"] == "ARCHIVED"


def test_rollback_and_audit_trail(reg, tmp_path):
    for v, f in (("v1", 0.7), ("v2", 0.8)):
        reg.register("classifier", v, f"m/{v}.joblib", metrics_file(tmp_path, v, real=f))
    reg.promote("classifier", "v1", by="a")
    reg.promote("classifier", "v2", by="b")
    assert reg.rollback("classifier", by="c")["version"] == "v1"
    assert reg.production("classifier")["version"] == "v1" and reg.get("classifier", "v2")["stage"] == "ARCHIVED"
    actions = [(h["action"], h.get("by")) for h in reg.data["history"]]
    assert actions[-3:] == [("promote", "a"), ("promote", "b"), ("rollback", "c")]
    with pytest.raises(GateError):
        ModelRegistry(reg.root).rollback("classifier")      # v1 has no previous production


def test_force_override_is_recorded_and_versions_are_immutable(reg, tmp_path):
    reg.register("classifier", "v1", "m/v1.joblib", metrics_file(tmp_path, "v1"))
    with pytest.raises(GateError, match="already registered"):
        reg.register("classifier", "v1", "other", None)
    reg.promote("classifier", "v1", by="boss", force=True)
    assert reg.data["history"][-1]["overridden"] == ["no REAL_TEST metrics"]
    assert ModelRegistry(reg.root).production("classifier")["version"] == "v1"      # persisted


def test_cli_and_production_path(tmp_path, capsys):
    root = str(tmp_path / "r")
    mf = metrics_file(tmp_path, "v1", real=0.8)
    assert registry_cli(["--root", root, "register", "classifier", "v1", "x.joblib", mf]) == 0
    assert registry_cli(["--root", root, "promote", "classifier", "v1", "--by", "me"]) == 0
    assert production_path("classifier", root) == "x.joblib"
    assert production_path("classifier", str(tmp_path / "empty")) is None
    assert registry_cli(["--root", root, "promote", "classifier", "nope"]) == 2


def test_api_serves_the_registry_production_model(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import app.api.main as main
    pipe = build("lr", 1.0).fit(["done", "pending", "please do it"] * 3, ["TASK_COMPLETED", "TASK_PENDING", "TASK"] * 3)
    clf_path = tmp_path / "m.joblib"
    MessageClassifier(pipe, "classifier_testv").save(clf_path)
    reg = ModelRegistry(tmp_path / "reg")
    reg.register("classifier", "classifier_testv", str(clf_path), metrics_file(tmp_path, "m", real=0.9))
    reg.promote("classifier", "classifier_testv", by="t")
    monkeypatch.delenv("CLASSIFIER_PATH", raising=False)
    monkeypatch.setenv("MODEL_REGISTRY_DIR", str(tmp_path / "reg"))
    main._clf_cache.clear()
    log = tmp_path / "preds.jsonl"
    monkeypatch.setenv("PREDICTION_LOG", str(log))
    c = TestClient(main.app)
    assert c.get("/ai/model").json()["classifier"] == "classifier_testv"
    body = {"project_id": "P9", "messages": [{"id": "a", "text": "Amit please integrate Razorpay by Friday", "sender": "Rahul", "ts": "2026-10-01T10:00:00", "index": 0},
                                              {"id": "b", "text": "Razorpay API integrated", "sender": "Amit", "ts": "2026-10-02T10:00:00", "index": 1}]}
    assert c.post("/ai/analyze-messages", json=body).status_code == 200
    rows = PredictionLogger.read(log)
    assert len(rows) == 2 and rows[0]["project_id"] == "P9" and rows[0]["model_version"] == "classifier_testv"
    assert all("text" not in r and "message" not in r for r in rows)                  # privacy: no message text in the log


def preds(label_probs, conf, lang="en", n=400):
    out = []
    for i in range(n):
        lab = next(l for l, c in zip(label_probs, __import__("itertools").accumulate(label_probs.values())) if (i + 0.5) / n <= c)
        out.append({"label": lab, "confidence": conf, "language": lang})
    return out


def test_psi_basics():
    same = {"a": 0.5, "b": 0.5}
    assert psi(same, same) == pytest.approx(0, abs=1e-6)
    assert psi({"a": 0.9, "b": 0.1}, {"a": 0.4, "b": 0.6}) > 0.2


def test_drift_detection_flags_and_ok():
    base = summarize(preds({"TASK": 0.4, "GENERAL": 0.6}, 0.9))
    ok = check_drift(base, summarize(preds({"TASK": 0.42, "GENERAL": 0.58}, 0.89)))
    assert ok["status"] == "OK" and ok["flags"] == []
    bad = check_drift(base, summarize(preds({"TASK": 0.1, "GENERAL": 0.9}, 0.6, lang="hinglish")), correction_rate=0.4)
    assert bad["status"] == "DRIFT" and len(bad["flags"]) >= 4
    assert check_drift(base, summarize(preds({"TASK": 1.0}, 0.9, n=10)))["status"] == "INSUFFICIENT_DATA"
