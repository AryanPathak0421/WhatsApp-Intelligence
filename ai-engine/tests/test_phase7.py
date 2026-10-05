import numpy as np
import pytest

from app.embeddings.embedder import HashingEmbedder
from app.embeddings.index import VectorIndex
from app.embeddings.linker import SemanticLinker
from app.intelligence.pipeline import analyze
from app.intelligence.types import Msg
from app.knowledge_graph.graph import build_graph, explain_blocked, to_node_link
from app.parsers.whatsapp import WhatsAppParser
from app.search.semantic import BM25, ProjectSearch
from tests.scenario_chat import CHAT


def parse(chat):
    return [Msg.from_parsed(m) for m in WhatsAppParser().parse_text(chat)]


@pytest.fixture(scope="module")
def msgs():
    return parse(CHAT)


@pytest.fixture(scope="module")
def result(msgs):
    return analyze(msgs)


# ------------------------------------------------------------------ vector index
def test_index_search_filters_and_idempotent(tmp_path):
    idx = VectorIndex("p1", 4, "m")
    v = np.eye(4, dtype=np.float32)
    assert idx.add(["a", "b", "c", "d"], v, [{"s": "x"}, {"s": "y"}, {"s": "x"}, {"s": "y"}]) == 4
    assert idx.add(["a", "e"], np.eye(4, dtype=np.float32)[:2], [{"s": "x"}, {"s": "x"}]) == 1  # 'a' is a duplicate
    top = idx.search(np.array([0, 1, 0, 0], np.float32), k=2)
    assert top[0][0] == "b" and top[0][1] == pytest.approx(1.0)
    only_x = idx.search(np.array([0, 1, 0, 0], np.float32), k=5, flt=lambda m: m["s"] == "x")
    assert only_x and all(h[2]["s"] == "x" for h in only_x)
    idx.save(tmp_path / "i.npz")
    again = VectorIndex.load(tmp_path / "i.npz")
    assert again.ids == idx.ids and again.project_id == "p1"


def test_bm25_ranks_matching_doc_first():
    b = BM25([["razorpay", "integr"], ["login", "screen"], ["deploy", "server"]])
    assert int(np.argmax(b.scores(["razorpay"]))) == 0 and b.scores(["unknownword"]).sum() == 0


# ------------------------------------------------------------------------ search
def test_search_hybrid_context_and_alias_expansion(msgs):
    ps = ProjectSearch("p1", HashingEmbedder())
    assert ps.add_messages(msgs) > 5
    assert ps.add_messages(msgs) == 0  # idempotent
    hits = ps.search("payment", k=5, mode="lexical")  # 'payment' must reach Razorpay via alias group
    assert any("Razorpay" in h["text"] for h in hits)
    h = hits[0]
    assert h["message_id"] and h["sender"] and h["context"]
    assert all(c["message_id"] != h["message_id"] for c in h["context"])


def test_search_filters_by_sender(msgs):
    ps = ProjectSearch("p1", HashingEmbedder())
    ps.add_messages(msgs)
    hits = ps.search("payment api", k=10, sender="Karan")
    assert hits and all(h["sender"] == "Karan" for h in hits)
    assert ps.search("payment", sender="Nobody") == []


def test_projects_are_isolated(msgs):
    a, b = ProjectSearch("A", HashingEmbedder()), ProjectSearch("B", HashingEmbedder())
    a.add_messages(msgs)
    assert b.search("razorpay") == [] and a.index.project_id == "A"


# --------------------------------------------------------- semantic linker (model)
MINILM = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def _hf(name):
    pytest.importorskip("transformers")
    from app.embeddings.embedder import HFEmbedder
    try:
        return HFEmbedder(name)
    except Exception as e:  # model not cached and no network
        pytest.skip(f"embedding model unavailable: {e}")


def test_semantic_linker_rescues_paraphrase_without_false_link():
    from tests.paraphrase_chat import CHAT as PCHAT
    lexical = analyze(parse(PCHAT))
    semantic = analyze(parse(PCHAT), linker=SemanticLinker(_hf(MINILM)))
    dark_lex = next(t for t in lexical["tasks"] if "dark" in t["title"])
    dark_sem = next(t for t in semantic["tasks"] if "dark" in t["title"])
    assert dark_lex["status"] == "TODO" and dark_sem["status"] == "COMPLETED"  # 'night theme implemented'
    # 'weather widget completed' is unrelated: it must not be attached to any task
    linked = {mid for t in semantic["tasks"] for mid in t["evidence_message_ids"]}
    weather = next(m for m in parse(PCHAT) if "weather" in m.text)
    assert weather.id not in linked


# ------------------------------------------------------------------------- graph
def test_graph_edges_and_evidence(result, msgs):
    G = build_graph(result, msgs)
    rels = {d["rel"] for _, _, d in G.edges(data=True)}
    assert {"ASSIGNED_TO", "CREATED", "COMPLETED", "SUPPORTS", "REQUESTED_FROM", "CHANGED"} <= rels
    amit_task = next(n for n, d in G.nodes(data=True) if d["kind"] == "Task" and "Razorpay" in d["title"])
    assert any(G.nodes[u]["name"] == "Amit" for u, _, d in G.in_edges(amit_task, data=True) if d["rel"] == "COMPLETED")
    assert all(d["source_message_ids"] for _, _, d in G.edges(data=True))
    assert to_node_link(G)["nodes"]


def test_blocked_explained_from_graph(result, msgs):
    G = build_graph(result, msgs)
    login = next(n for n, d in G.nodes(data=True) if d["kind"] == "Task" and "login" in d["title"])
    e = explain_blocked(G, login)
    assert "credentials" in e["text"] and e["source_message_ids"]
    done = next(n for n, d in G.nodes(data=True) if d["kind"] == "Task" and "Razorpay" in d["title"])
    assert explain_blocked(G, done) is None


def test_client_block_edge_and_insight():
    chat = ("01/10/2026, 10:00 - Rahul: Amit please integrate Razorpay by Friday\n"
            "01/10/2026, 10:30 - Amit: Razorpay ka kaam ho gaya but waiting for client credentials\n"
            "01/10/2026, 11:00 - Sales - Neha: Waiting for client to send Razorpay credentials\n"
            "05/10/2026, 11:00 - Rahul: ok\n")
    ms = parse(chat)
    r = analyze(ms)
    G = build_graph(r, ms)
    assert any(d["rel"] == "BLOCKED_BY" for _, _, d in G.edges(data=True))
    text = " ".join(i["text"] for i in r["insights"] if i["kind"] == "BLOCKER")
    assert "razorpay" in text.lower() and "client credentials" in text and "pending" in text


# ----------------------------------------------------- decisions / meetings / actions
def test_decisions_and_meetings():
    chat = ("01/10/2026, 10:00 - Rahul: We have decided to go with PostgreSQL\n"
            "01/10/2026, 10:30 - Rahul: Demo call tomorrow at 3 pm with client\n"
            "01/10/2026, 10:45 - Amit: did we decide the launch date?\n")
    r = analyze(parse(chat))
    assert len(r["decisions"]) == 1 and "PostgreSQL" in r["decisions"][0]["title"]
    assert len(r["meetings"]) == 1 and r["meetings"][0]["scheduled_at"].hour == 15


def test_next_actions_have_owner_priority_evidence(result):
    acts = result["next_actions"]
    assert acts
    fu = next(a for a in acts if a["action"].startswith("Follow up with the client"))
    assert fu["owner"] == "Sales - Neha" and fu["source_message_ids"]
    assert fu["priority"] in ("MEDIUM", "HIGH", "CRITICAL")
    assert any(a["action"].startswith("Verify conflicting") for a in acts)
