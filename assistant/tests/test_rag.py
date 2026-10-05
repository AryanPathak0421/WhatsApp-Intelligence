import pytest

from wa_assistant.llm.base import LLMOutput
from wa_assistant.llm.scripted import ScriptedLLM, call
from wa_assistant.rag.cite import ABSTAIN, finalize, should_abstain
from wa_assistant.rag.ingest import build_document
from wa_assistant.rag.store import DocumentStore

pytestmark = pytest.mark.anyio

LORA = b"""# LoRA: Low-Rank Adaptation of Large Language Models

Edward Hu et al. 2021. DOI 10.48550/arXiv.2106.09685

Abstract
We propose Low-Rank Adaptation, which freezes the pretrained model weights and injects trainable rank decomposition matrices into each layer of the Transformer architecture. This greatly reduces the number of trainable parameters for downstream tasks.

## 1 Introduction
Fine-tuning every parameter of a large model is expensive. Low-rank adaptation trains small matrices instead of the full weights, so a single base model can serve many tasks.

## 2 Method
The update to a weight matrix is represented as the product of two small matrices. Only these matrices are trained while the original weights stay frozen. At inference the product can be merged into the base weights, so there is no added latency.

## References
[1] Vaswani et al. Attention is all you need.
"""

RAG = b"""# Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks

Abstract
We combine pre-trained parametric memory with a non-parametric memory, a dense vector index of Wikipedia, accessed with a neural retriever. The model generates answers conditioned on retrieved passages.

## 3 Models
The retriever is a bi-encoder that returns the top documents for a query. The generator is a sequence-to-sequence model that marginalises over the retrieved documents.
"""


def store(**meta):
    s = DocumentStore()
    for data, name, scope, m in ((LORA, "lora.md", "global", {"authors": ["Edward J. Hu", "Yelong Shen"], "year": 2021}), (RAG, "rag.md", "global", {"year": 2020})):
        d, ch = build_document(data, name, scope=scope, metadata=m)
        s.add(d, ch)
    return s


def test_ingestion_extracts_sections_metadata_and_never_invents_authors():
    d, ch = build_document(LORA, "lora.md")
    assert d.title.startswith("LoRA") and d.doi == "10.48550/arXiv.2106.09685" and d.authors == []        # authors only if supplied
    assert "freezes the pretrained model weights" in d.abstract
    assert {c.section for c in ch} >= {"Abstract", "Introduction", "Method"} and all(c.section != "References" for c in ch)
    assert all(c.parent_text and c.id.startswith(d.id) for c in ch)


def test_same_file_is_ingested_once():
    s = DocumentStore()
    d, ch = build_document(LORA, "lora.md")
    assert s.add(d, ch) is True and s.add(d, ch) is False


def test_hybrid_search_finds_the_right_passage_and_filters_by_metadata():
    s = store()
    r = s.search("how does low-rank adaptation reduce trainable parameters", k=3)
    assert r and "LoRA" in r[0]["title"] and r[0]["relevance"] > 0.4 and r[0]["citation"] == "C1"
    assert all(x["year"] >= 2021 for x in s.search("retriever passages", year_min=2021))
    assert s.search("retriever bi-encoder top documents", k=1)[0]["title"].startswith("Retrieval-Augmented")


def test_scope_isolation_project_documents_are_invisible_without_access():
    s = store()
    d, ch = build_document(b"# Internal pricing memo\n\nThe enterprise discount rate for Q3 is twelve percent for strategic accounts.", "memo.md", scope="proj-1")
    s.add(d, ch)
    assert not s.search("enterprise discount rate", {"global"})
    assert s.search("enterprise discount rate", {"global", "proj-1"})


def test_unanswerable_questions_abstain():
    s = store()
    r = s.search("what is the boiling point of tungsten", k=3)
    assert should_abstain(r, 0.2)
    assert not should_abstain(s.search("low-rank adaptation of weights", k=3), 0.2)


def test_citation_finalizer_removes_fabrications_and_builds_references_from_metadata():
    s = store()
    res = s.search("low-rank adaptation frozen weights", k=2)
    quote = res[0]["text"][:60].rstrip()
    answer = (f'LoRA freezes the pretrained weights [C1]. It was invented by Bob [C9]. As the paper says, "{quote}" and also '
              f'"this sentence appears nowhere in any retrieved passage at all". See doi 10.9999/fake.123 and https://evil.example/x.')
    f = finalize(answer, res)
    assert "[C9]" not in f.text and "evil.example" not in f.text and "10.9999/fake.123" not in f.text
    assert '"this sentence appears nowhere' not in f.text and f"\"{quote}\"" in f.text
    assert "References:" in f.text and "Edward J. Hu" in f.text and "10.48550/arXiv.2106.09685" in f.text
    assert len(f.issues) >= 3


def test_answer_without_any_citation_is_labelled_unverified():
    res = store().search("low-rank adaptation", k=2)
    assert "Unverified" in finalize("LoRA is great.", res).text


def test_authors_not_recorded_is_stated_not_guessed():
    s = DocumentStore()
    d, ch = build_document(RAG, "rag.md")
    s.add(d, ch)
    res = s.search("retriever bi-encoder", k=1)
    assert "authors not recorded" in finalize("The retriever is a bi-encoder [C1].", res).text


async def test_agent_answers_from_documents_with_verified_citations(make_env):
    docs = store()
    env = make_env(ScriptedLLM([LLMOutput(tool_calls=[call("search_documents", query="how does LoRA reduce trainable parameters")]),
                                LLMOutput(text="LoRA freezes the base weights and trains small rank-decomposition matrices [C1]. Latency stays the same [C7].")]),
                   documents=docs)
    r = await env.say(env.session("pm"), "What does the LoRA paper say about trainable parameters?")
    assert "documents" in r.sources and r.citations and r.citations[0]["title"].startswith("LoRA")
    assert "[C7]" not in r.reply and "References:" in r.reply


async def test_agent_abstains_without_calling_the_model_again_when_evidence_is_missing(make_env):
    llm = ScriptedLLM([LLMOutput(tool_calls=[call("search_documents", query="boiling point of tungsten")]), LLMOutput(text="It is 5555 C [C1].")])
    env = make_env(llm, documents=store())
    r = await env.say(env.session("pm"), "What is the boiling point of tungsten?")
    assert r.abstained and ABSTAIN in r.reply and len(llm.calls) == 1


async def test_project_documents_need_proven_project_access(make_env):
    docs = store()
    d, ch = build_document(b"# Beta confidential plan\n\nThe launch budget for the Beta programme is forty thousand dollars.", "beta.md", scope="22222222-bbbb-4bbb-8bbb-222222222222")
    docs.add(d, ch)
    llm = ScriptedLLM([LLMOutput(tool_calls=[call("list_projects")]),
                       LLMOutput(tool_calls=[call("search_documents", query="Beta programme launch budget", project_id="22222222-bbbb-4bbb-8bbb-222222222222")]),
                       LLMOutput(text="x")])
    env = make_env(llm, documents=docs)
    r = await env.say(env.session("pm"), "what is the Beta launch budget?")           # the PM is not a member of Beta: list_projects never returns it
    assert not r.citations and not any("forty thousand" in str(m.get("content")) for m in env.session("pm").messages)


def _pdf(pages: list[list[str]]) -> bytes:
    """Minimal valid PDF (Helvetica text, one content stream per page) so PDF ingestion is tested without any PDF library."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for lines in pages:
        content = "BT /F1 11 Tf 14 TL 50 740 Td " + " ".join(f"({l.replace('(', '[').replace(')', ']')}) Tj T*" for l in lines) + " ET"
        objs.append(f"<< /Length {len(content)} >>\nstream\n{content}\nendstream")
        cid = len(objs)
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {cid} 0 R /Resources << /Font << /F1 3 0 R >> >> >>")
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    return out + f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()


def test_pdf_ingestion_keeps_page_numbers():
    import shutil
    if not shutil.which("pdftotext"):
        pytest.skip("poppler not installed")
    pdf = _pdf([["Attention Mechanisms for Summarisation", "ABSTRACT", "We study attention mechanisms for long document summarisation in detail."],
                ["2 Results", "The attention model improves ROUGE scores on every benchmark we tried across languages."]])
    d, ch = build_document(pdf, "paper.pdf", scope="global", metadata={"year": 2024})
    assert d.n_pages == 2 and d.title.startswith("Attention Mechanisms")
    s = DocumentStore()
    s.add(d, ch)
    r = s.search("which scores improve with the attention model", k=1)
    assert r and r[0]["page"] == 2


def test_corrupt_pdf_is_rejected_cleanly():
    import shutil
    if not shutil.which("pdftotext"):
        pytest.skip("poppler not installed")
    with pytest.raises(ValueError):
        build_document(b"%PDF-1.4 this is not really a pdf", "bad.pdf")
