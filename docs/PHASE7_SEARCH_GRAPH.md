# Phase 7 - Semantic search, embeddings, knowledge graph

Code: `app/embeddings/` (embedder, per-project index, linker), `app/search/semantic.py`, `app/knowledge_graph/graph.py`,
`app/intelligence/decisions.py`. API: `/ai/embeddings`, `/ai/index`, `/ai/search`, `/ai/graph`; `/ai/analyze` now also returns
`decisions`, `meetings`, `insights`, `next_actions`, `graph_stats`.

## Embedding benchmark (`python -m app.evaluation.embedding_benchmark`)
Probe: 42 messages / 15 queries / 36 task-message pairs, handwritten (EN + Hinglish). Small: pick candidates, not proof.
| Model | recall@3 | MRR | pair AUC | pos mean / neg mean cosine | dim |
|---|---|---|---|---|---|
| hashing (baseline) | 0.39 | 0.69 | 0.69 | 0.16 / 0.01 | 384 |
| multilingual-e5-small | 0.69 | 0.93 | 0.80 | 0.89 / 0.86 (compressed) | 384 |
| paraphrase-multilingual-MiniLM-L12-v2 | 0.59 | 0.90 | 0.86 | 0.43 / 0.12 (well separated) | 384 |
| bge-small-en-v1.5 (English only) | 0.74 | 1.00 | 0.86 | 0.67 / 0.49 | 384 |
Latency was measured while a training job was running, so treat ms/msg as unreliable (MiniLM-L12 was ~10x slower than e5-small/bge-small here).
Choice (provisional): **search = multilingual-e5-small + BM25 hybrid** (multilingual, fast); **task linking = MiniLM-L12 with a calibrated cosine profile**
(only model with a clear positive/negative gap). Differences of ~0.05 AUC on 36 pairs are noise.

## Hybrid search
Semantic cosine + BM25 (alias-expanded: "payment" reaches Razorpay / gateway) fused with reciprocal-rank fusion. Filters: sender, date. Every hit is an
original message plus +/-2 context messages. One index per project; `VectorIndex.add` is idempotent (incremental import). Exact numpy search
(faiss has no wheel for Python 3.14 here); production stores vectors in pgvector (`MessageEmbedding`) - same vectors, SQL `<=>` ordering.

## Semantic task linking
`build_tasks(..., linker=SemanticLinker(emb))` lets embeddings supply the topic-overlap term. On a hard handwritten paraphrase chat (follow-ups by a
non-assignee sharing no words with the task), MiniLM linked 1 of 3 paraphrases ("night theme implemented" -> "dark mode") and correctly refused the
unrelated "weather widget completed"; it missed "downloadable bill generation" -> "invoice PDF export" and "favourites list" -> "wishlist". So: helpful,
not a fix. The linker is OFF by default; synthetic-suite scores are unchanged either way. Also tightened the context fallback (a message only attaches to
the sender's last task when it has no content words, e.g. "Done"), removing a false link found while testing.

## Knowledge graph (NetworkX)
Nodes: Person, Task, ClientPending, Requirement, Bug, Decision, Meeting, Message (cited only). Edges: ASSIGNED_TO, CREATED, COMPLETED, BLOCKED_BY,
DEPENDS_ON (weak, from blocked-message topic), REQUESTED_FROM, REPORTED, AFFECTS, CHANGED/REQUESTED, DECIDED, SUPPORTS. Every edge has confidence and
source message ids (tested). `explain_blocked` renders sentences like "Razorpay integration is blocked because client credentials is pending (4 days)"
strictly from graph paths. `next_actions` turns open client dependencies, overdue tasks, unassigned tasks and conflicts into
{action, owner, priority, deadline, source_message_ids, reason, confidence}.

## Limits
- Hinglish retrieval quality is only checked on 15 handwritten queries.
- Decisions/meetings are rule-based (keyword + time extraction), not model-based; no scoring against real data yet.
- Graph DEPENDS_ON is a heuristic; treat as a hint.
