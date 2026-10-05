from app.datasets.split import split_records
from app.datasets.synthetic import generate_project
from app.labels import CATEGORIES
from app.parsers.whatsapp import WhatsAppParser


def test_roundtrip_all_styles():
    seen_styles = set()
    for seed in range(12):
        chat, gold, style = generate_project(seed, f"p{seed}", n_tasks=8)
        seen_styles.add(style)
        msgs = WhatsAppParser().parse_text(chat)
        assert len(msgs) == len(gold)
        for m, g in zip(msgs, gold):
            assert m.is_system == bool(g.get("is_system"))
            assert m.text == g["message"].strip()
            assert m.sender_name == g["sender"]
            assert g["category"] in CATEGORIES
    assert len(seen_styles) == 3


def test_deterministic():
    assert generate_project(3, "x")[0] == generate_project(3, "x")[0]


def test_split_by_project_no_leakage():
    recs = [{"project_id": f"p{i % 10}", "i": i} for i in range(100)]
    parts = split_records(recs)
    owners = {}
    for name, rows in parts.items():
        for r in rows:
            assert owners.setdefault(r["project_id"], name) == name
    syn = split_records(recs, allow_test=False)
    assert "test" not in syn
