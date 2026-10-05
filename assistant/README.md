# Project Intelligence assistant

A policy-governed AI assistant for the application: it answers questions, searches cited documents, and carries out actions **as the signed-in
user**. Design and literature review: [`docs/assistant/ARCHITECTURE.md`](../docx/07-assistant/ARCHITECTURE_AND_LITERATURE.md).

```
user (text) -> /assistant/chat -> agent loop: model proposes a tool call
                                  -> policy engine (deterministic): schema, ids seen earlier, rate limit, tier, taint
                                  -> executor: backend API with the USER's token (role + project membership enforced by the backend)
                                  -> verifier: reads the change back
                                  -> reply = model text + a system-written report of what actually happened
sensitive (T2) actions stop at a pending confirmation; only POST /assistant/confirm (the UI button) executes them.
```

## Status (what is real and what is not)

| Part | State |
|---|---|
| Tool registry, policy engine, executor, verifier, pending/confirm, audit log, sessions | Implemented, tested (sandbox backend **and** the real backend via `scripts/live_smoke.py`) |
| Prompt-injection defences (wrapped untrusted data, taint-then-confirm, T3 refusal, id provenance, user-token authorization) | Implemented; tested against a worst-case "obedient" model |
| RAG: ingestion (PDF/MD/TXT/HTML), parent/child chunks, BM25 + dense + metadata filters + RRF + rerank, citation verification, abstention | Implemented, tested. Default reranker is lexical (cannot match paraphrases); dense embedder is hashing unless you plug in an e5/BGE encoder |
| Evaluation harness (state-diff, 37 cases EN/Hinglish, oracle/adversary/real-model modes) | Implemented. Only the oracle and adversary have been run |
| React chat panel (confirm/cancel buttons, sources, citations, feedback) | Implemented, checked in the browser against the mock model + real backend |
| Voice: endpointing/barge-in state machine, WAV upload endpoint, ASR adapter interface | Implemented with doubles. **No speech model is installed**, so real ASR/TTS accuracy and latency are unmeasured; `/assistant/voice` answers 501 until an ASR is configured |
| **A real self-hosted LLM** | **Not installed.** This machine has no GPU (CPU, 15.7 GB RAM) and no model weights. Nothing about the language model's tool-calling quality has been measured |
| Fine-tuning, preference tuning, drift monitoring of the assistant | Not started (design only, see ARCHITECTURE.md section 9) |

## Run

```bash
cd assistant
pip install -r requirements.txt            # the ai-engine virtualenv already has everything
python -m pytest -q                        # 57 tests, no model or network needed
python -m wa_assistant.eval.run_eval --oracle      # harness self-test
python -m wa_assistant.eval.run_eval --adversary   # worst-case model vs. the safety layers

# service (needs the application backend and an OpenAI-compatible model server)
BACKEND_URL=http://localhost:4000/api LLM_BASE_URL=http://localhost:8080/v1 LLM_MODEL=<model> python -m wa_assistant   # :8100
```

The frontend proxies `/assistant` to `:8100` (`VITE_ASSISTANT_TARGET`).

### Model server (self-hosted, no external API)

Any server that speaks the OpenAI chat-completions protocol with `tools` works: llama.cpp `llama-server`, Ollama, vLLM. Choose the model with the
bake-off, not by popularity:

```bash
python -m wa_assistant.eval.run_eval --llm-url http://localhost:8080/v1 --model <name> --out report-<name>.json --verbose
```

Compare candidates on success rate (with its confidence interval), tool-selection rate, safety violations (must be 0), p50/p95 latency on YOUR hardware.
`scripts/mock_llm_server.py` is a rule-based stand-in used only to check the UI; it is not a language model.

## Safety model in one paragraph

The model never holds authority. Reads run immediately. Writes are typed, validated, rate-limited and executed with the user's own token, so the
backend's role matrix and project membership apply (a viewer cannot create tasks through the assistant; a project the user cannot see answers 404).
Ids must come from an earlier lookup. Tier T2 (complete/cancel task, add member) and any write that follows text read from documents or chats need an
explicit button press. Tier T3 (delete, roles, payments, external messages, exports) is refused in chat. Every write is read back, and the reply
states `verified`, `not independently verified` or `mismatch` from executor results, not from the model's own claim. Audit entries record who, what,
the policy decision and the outcome, never message text. Known limit: no technique makes an LLM fully injection-proof; the design bounds the damage.

## Files

| Path | Purpose |
|---|---|
| `wa_assistant/tools/registry.py` | the only actions available; arguments, tiers, endpoint mapping, verification |
| `wa_assistant/policy.py` | allow / confirm / refuse / invalid |
| `wa_assistant/agent.py`, `executor.py`, `pending.py`, `session.py`, `audit.py` | loop, execution, confirmations, per-user state, audit |
| `wa_assistant/rag/` | ingest, store (hybrid search), rerank, cite (grounding checks) |
| `wa_assistant/voice/` | endpointing / barge-in, ASR adapters |
| `wa_assistant/eval/` | sandbox backend, cases (`cases/make_cases.py`), runner |
| `scripts/live_smoke.py` | contract check against the real backend (creates a project in that database) |
