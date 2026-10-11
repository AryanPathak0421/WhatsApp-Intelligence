# Search and RAG

Two separate retrieval systems share the same ideas (hybrid lexical + dense, evidence ids, no fabricated references).

## 1. Project message search (`ai-engine/app/search/semantic.py`)
Indexes a project's stored messages: in-app project-group messages (mirrored into `ChatMessage`) and messages kept from the former WhatsApp import. Direct messages and groups without a project are never indexed.
Per-project index (one index = one project, hard isolation): BM25 over stemmed tokens (with domain alias expansion, e.g. "payment" also matches razorpay/gateway) + dense vectors
(multilingual-e5 or the dependency-free hashing embedder) + filters (sender, date range); modes `hybrid | semantic | lexical`; fusion by reciprocal rank. Endpoints `POST /ai/index`,
`POST /ai/search`, `DELETE /ai/index/{project}` (retention). The index lives in the engine's memory and is rebuilt by analysis; erasing/purging a project drops it.
Evaluation and the benchmark on synthetic and unseen chats (WhatsApp-format text files used as an evaluation dataset): `docs/PHASE7_SEARCH_GRAPH.md`.

## 2. Document / research-paper RAG (`assistant/wa_assistant/rag/`)

```
file (PDF/MD/TXT/HTML) -> parse -> section detection -> metadata -> parent chunks (sections, <=3000 chars) -> child chunks (~520 chars, 1 sentence overlap)
query -> BM25 + dense + metadata filters (year, tag, scope, doc) -> RRF -> rerank -> top-k with relevance 0..1 -> [abstain if best < threshold] -> LLM (passages wrapped as untrusted)
answer -> citation check -> references built from stored metadata
```

- **Ingestion** (`ingest.py`): PDFs via poppler `pdftotext` (temp file; some builds lack stdin support), HTML via a stripping parser, headings from Markdown, numbered or all-caps section names;
  reference lists are not indexed. Metadata: title (heuristic), DOI and year (regex on the first page), abstract; **authors are never guessed**: empty unless supplied by the uploader. Same file = same id (content hash).
- **Scope = access control**: `global` (shared library) is visible to every signed-in user; project documents only when the backend confirms the user can see that project (`GET /projects/:id` with the user's token).
- **Retrieval** (`store.py`): per-query BM25 + dense over the allowed chunks, RRF fusion (k=60), top 40 candidates to the reranker.
- **Reranker** (`rerank.py`): default `LexicalReranker` (weighted coverage + bigram bonus). It cannot match paraphrases, so abstention is more frequent than ideal. `CrossEncoderReranker` (BGE-class, local weights) exists
  but is **untested here** (no weights installed).
- **Abstention**: if the best relevance is below `RAG_ABSTAIN_BELOW` (default 0.2) the assistant answers "I don't have enough verified information to answer that confidently" without calling the model.
- **Citation checking** (`cite.py`): markers `[C1]` must exist in the retrieved set (others removed); quotes of 25+ characters must appear in a cited passage (else un-quoted and reported); DOIs/URLs not in
  stored metadata are removed; the reference list (title, authors or "authors not recorded", year, DOI, page) is generated from metadata; an answer using retrieved material but citing nothing is labelled unverified.
- **Provenance classes** in every reply: application data, documents (cited), what the user said, model general knowledge (marked unverified).

### Tests
`assistant/tests/test_rag.py` (13): sections/metadata, no invented authors, idempotent ingest, hybrid ranking + filters, scope isolation, abstention, citation finalizer removes fabrications, PDF page numbers,
corrupt PDF rejected, end-to-end agent answers with verified citations, abstains without a second model call, project documents need proven access. `assistant/tests/test_api.py` covers upload permissions.

### Not done
No real corpus of papers is loaded; no embedding/reranker benchmark on Hinglish; no query rewriting, multi-query, HyDE or GraphRAG (listed in the literature review; to be adopted only if they beat the baseline on a labelled
set). Paper-specific entities (figures, tables, equations) are plain text.
