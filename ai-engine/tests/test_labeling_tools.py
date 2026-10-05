import json

import pytest

from app.datasets.anonymize import anonymize_text
from app.evaluation.agreement import cohen_kappa, compare, load
from app.intelligence.pipeline import analyze
from app.intelligence.types import Msg
from app.parsers.whatsapp import WhatsAppParser

CHAT = """[01/10/2026, 10:00 AM] Rahul Sharma: Amit, please call +91 98765 43210 or mail amit@acme.com about the invoice 123456789
[01/10/2026, 10:05 AM] Amit Verma: Rahul I will check https://acme.atlassian.net/browse/X-1 today
[01/10/2026, 10:10 AM] Sales - Neha: Waiting for client confirmation from Mr. Kapoor
[01/10/2026, 10:11 AM] Anjali (Client): Neha, approved from my side
[01/10/2026, 10:12 AM] ‎Rahul Sharma added Priya
"""


def test_anonymisation_masks_identifiers_and_names():
    out, mapping = anonymize_text(CHAT)
    for leaked in ("Rahul", "Sharma", "Amit", "Verma", "Neha", "Anjali", "Priya", "98765", "amit@acme.com", "atlassian", "123456789"):
        assert leaked not in out, leaked
    assert "<phone>" in out and "<email>" in out and "<url>" in out and "<system message>" in out
    assert set(mapping["senders"]) == {"Rahul Sharma", "Amit Verma", "Sales - Neha", "Anjali (Client)"}
    assert mapping["senders"]["Sales - Neha"].endswith("(Sales)") and mapping["senders"]["Anjali (Client)"].endswith("(Client)")


def test_anonymised_chat_still_parses_and_roles_survive():
    out, _ = anonymize_text(CHAT)
    msgs = WhatsAppParser().parse_text(out)
    assert len(msgs) == 5 and msgs[4].is_system
    res = analyze([Msg.from_parsed(m) for m in msgs])
    roles = {n: r["role"] for n, r in res["roles"].items()}
    assert "SALES" in roles.values() and "CLIENT" in roles.values()    # role hints in sender names are kept for the role engine


def test_pseudonyms_are_consistent():
    out, mapping = anonymize_text(CHAT)
    rahul = mapping["senders"]["Rahul Sharma"].split(" (")[0]
    assert out.count(rahul) >= 2     # the sender line plus the mention inside the other person's message


def test_kappa_known_values():
    assert cohen_kappa(list("aabb"), list("aabb")) == 1.0
    assert cohen_kappa(list("aabb"), list("bbaa")) == -1.0
    # 80% observed agreement, balanced classes -> kappa 0.6
    a = ["x"] * 5 + ["y"] * 5
    b = ["x"] * 4 + ["y"] + ["y"] * 4 + ["x"]
    assert cohen_kappa(a, b) == pytest.approx(0.6)
    with pytest.raises(ValueError):
        cohen_kappa([], [])


def test_compare_files(tmp_path):
    def write(name, labels):
        p = tmp_path / name
        p.write_text("\n".join(json.dumps({"project_id": "p", "message_id": f"m{i}", "category": c}) for i, c in enumerate(labels)))
        return p
    a = write("a.jsonl", ["TASK"] * 10 + ["GENERAL"] * 10)
    b = write("b.jsonl", ["TASK"] * 9 + ["REQUIREMENT"] + ["GENERAL"] * 10)
    r = compare(load(a), load(b))
    assert r["n_overlap"] == 20 and r["agreement"] == 0.95 and r["kappa"] > 0.7 and r["verdict"] == "OK for training"
    assert r["top_disagreements"][0] == {"a": "TASK", "b": "REQUIREMENT", "count": 1}


def test_mentions_extra_redactions_and_role_hints():
    chat = ("[01/10/2026, 10:00 AM] Asha Rao: Hi @\u2068~Karan Mehta\u2069 please check the Acme Ltd site\n"
            "[01/10/2026, 10:05 AM] Dev One: @\u2068~Asha Rao\u2069 sure, will do\n")
    out, mp = anonymize_text(chat, redact={"Acme Ltd": "ClientCo"}, roles={"Asha Rao": "Client"})
    for leaked in ("Karan", "Mehta", "Asha", "Rao", "Acme"):
        assert leaked not in out, leaked
    assert "ClientCo" in out and "@Mention 1" in out
    assert mp["senders"]["Asha Rao"].endswith("(Client)")
    assert "@Person A" in out                                   # a mention of a known sender reuses that sender's pseudonym


def test_pasted_credentials_are_masked_but_normal_words_survive():
    chat = ("[01/10/2026, 10:00 AM] Asha: SMS key ; fk64EXAMPLEkeyABCdefGh\n"
            "[01/10/2026, 10:01 AM] Asha: password: Zx9@kLm2 and token=abcDEF123456ghiJKL789\n"
            "[01/10/2026, 10:02 AM] Asha: the key feature is ready, keyboard shortcuts and 2FA done\n")
    out, _ = anonymize_text(chat)
    assert "fk64EX" not in out and "Zx9" not in out and "abcDEF" not in out
    assert out.count("<secret>") >= 3
    assert "key feature is ready" in out and "keyboard shortcuts" in out


def test_labelled_and_complex_passwords_are_masked():
    chat = ("[01/10/2026, 10:00 AM] Asha: Website :- https://x.example.com\n"
            "[01/10/2026, 10:00 AM] Asha: User Id :- asha@acme.com\n"
            "[01/10/2026, 10:00 AM] Asha: User Name :- acmeadmin\n"
            "[01/10/2026, 10:00 AM] Asha: password :- Acme!@#123\n"
            "[01/10/2026, 10:01 AM] Asha: acme@x.com\n#acme@8779\n"
            "[01/10/2026, 10:02 AM] Asha: login: ravi_k and pwd = s3cretWord\n"
            "[01/10/2026, 10:03 AM] Asha: the password policy needs review and the key feature is ready\n")
    out, _ = anonymize_text(chat)
    for leaked in ("acmeadmin", "Acme!@#123", "#acme@8779", "ravi_k", "s3cretWord", "acme@x.com"):
        assert leaked not in out, leaked
    assert "password policy needs review" in out and "key feature is ready" in out      # ordinary prose is untouched
