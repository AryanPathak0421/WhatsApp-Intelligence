from app.classifiers.baseline import MessageClassifier, build
from app.datasets.synthetic import generate_project
from app.evaluation.metrics import calibration_table, evaluate
from app.labels import CATEGORIES


def _rows(seeds):
    rows = []
    for s in seeds:
        rows += generate_project(s, f"p{s}")[1]
    return [r for r in rows if not r.get("is_system")]


def test_train_predict_save_load(tmp_path):
    tr, te = _rows(range(30)), _rows(range(100, 110))
    pipe = build("lr", 5.0).fit([r["message"] for r in tr], [r["category"] for r in tr])
    clf = MessageClassifier(pipe, "classifier_test")
    out = clf.predict([r["message"] for r in te[:20]])
    assert all(0 <= o["confidence"] <= 1 and o["model_version"] == "classifier_test" for o in out)
    assert all(len(o["alternatives"]) == 2 for o in out)
    clf.save(tmp_path / "m.joblib")
    again = MessageClassifier.load(tmp_path / "m.joblib").predict([te[0]["message"]])
    assert again[0]["category"] == out[0]["category"]


def test_metrics_shapes():
    m = evaluate(["TASK", "BUG"], ["TASK", "TASK"], CATEGORIES)
    assert m["accuracy"] == 0.5 and len(m["confusion_matrix"]) == len(CATEGORIES)
    assert m["per_class"]["BUG"]["recall"] == 0.0
    cal = calibration_table([0.99, 0.4], [True, False])
    assert sum(b["n"] for b in cal) == 2
