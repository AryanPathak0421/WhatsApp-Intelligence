# Phase 11 - Testing, benchmarking, hardening

## 1. Test inventory (all green at the end of this phase)
| Component | Tests | What they cover |
|---|---|---|
| ai-engine (pytest) | 122 | parser, synthetic data, annotation, classifier, Phase 5-8 engines, search/graph, reports/exports, API, **robustness/fuzz + ReDoS**, **round-2 regression tests** |
| backend (vitest) | 46 | auth/JWT/refresh rotation, RBAC + project isolation, upload validation, duplicate + incremental import, human-override survival, encryption, failure handling, BullMQ on real Redis, overview/executive |
| frontend (vitest) | 10 | formatters, permission mirror, badges, token-refresh de-duplication, login validation |

Backend tests run against real PostgreSQL + the real Python engine (and Redis for BullMQ). No mocks of our own code.

## 2. The most important result: accuracy on chats the rules were not written for
`python -m bench.unseen_eval` scores the engines on hand-written realistic chats (`eval/unseen/`, English / Hinglish / noisy, 6 chats, 138 messages) with gold labels written
BEFORE running anything. The synthetic-suite numbers from Phase 5 (task F1 0.997, etc.) are template coverage and say nothing about this.

| Set | How it was used | Tasks found | Task final status correct | Client-pending found / state right | Req. change | Bugs found / final state |
|---|---|---|---|---|---|---|
| a-c (3 chats), **first run** | untouched | 5/8 (62%) | 3/8 (38%) | **0/4 (0%)** | 1/1 | 2/2 / 50% |
| d-e (2 chats), **first run** | holdout | 1/5 (20%) | 1/5 (20%) | 3/3 / 1/3 | 0/1 | 1/1 / 0% |
| f (1 chat), run before any tuning | fresh holdout | 1/3 (33%) | 1/3 (33%) | 0/1 | n/a | 1/1 / 100% |
| **All untouched first runs** | | **7/16 (44%)** | **5/16 (31%)** | **3/8 found, 1/8 state right** | | |

So: **on unfamiliar phrasing the rule engine finds well under half the tasks and gets about a third of the final statuses right.** Client-pending detection was the weakest
(it only recognised phrasing like "client hasn't ...", not named clients such as "Mr Kapoor still hasn't sent the logo").

Two rounds of fixes were then made for the *generic* defects those failures revealed (122 tests still green, synthetic suite unchanged: final-status 0.884, completed-false-positive 1.1%):
sentence-level vocative detection ("Understood Dr. Rao. Tushar, do X"), `@mentions`, more Hinglish imperatives, volunteering ("need an owner" -> "I can take it"), self-announced tasks,
requests to / complaints about *named* client-side people, a client supplying the item resolving it (and an unrelated approval no longer closing it), client-assignee tasks
no longer treated as dev tasks, bug acknowledgement linking a later fix, "X instead of Y" requirement changes without a fixed option list, reachability wording in conflicts,
"final" decisions. After those fixes the same chats read: a-c tasks 8/8, d-e tasks 4/5 - **but these chats were used to find the fixes, so those numbers are tuned and must not be quoted
as accuracy.** The one fresh chat (f) was run before tuning on it and still scored 1/3 tasks, 0/1 client-pending, which is the realistic expectation (remaining misses there: "you own it",
"add retry ...", a dev asking *who has* the credentials, third-party hand-offs).

**Conclusion:** hand-written rules overfit the phrasing their author imagines. They are a useful, auditable baseline and a safety net, but reliable extraction needs the planned
learning loop (annotated real chats -> trained models, with these rules as features/fallback). `eval/unseen/` should be replaced/extended with real, human-labelled project chats; use fresh
files for any future before/after claim.

## 3. Performance (CPU only, synthetic chats; `python -m bench.bench_scale`, `backend/bench/api_bench.mjs`)
Engine, parse + full analysis:
| Messages | Before | After | Notes |
|---|---|---|---|
| 2,000 | 2.8 s | 0.5 s | |
| 10,000 | 27.2 s | 3.4 s | was quadratic (every engine re-ran regexes; every message scanned every task) |
| 30,000 | not measured (trend: many minutes) | 15.7 s | |
| 100,000 | not measured (trend: tens of minutes) | 130 s, peak 1.1 GB | 11k tasks (synthetic worst case) |
| 1,000,000 | - | **not supported** | would need chunked analysis and ~10 GB; documented gap |

Fixes: cached signals/normalisation/topic sets, inverted index for task linking (candidate pool capped at 200), bounded windows in conflict/commitment search, prefix-sum progress timeline,
cap on the key-message similarity matrix (it would have been N^2 = tens of GB at 100k).

Full import through the real HTTP API (upload -> parse -> store -> analyse -> index -> persist -> notify):
| Chat | Upload request | Job total | Duplicate re-upload |
|---|---|---|---|
| 10k messages (0.75 MB) | 59 ms (202) | 34 s | 409 in 41 ms |
| 30k messages (2.2 MB) | 87-250 ms (202) | 75-88 s | 409 in 54 ms |

Read latency, 10 concurrent clients, 30k-message project, after fixes (p50 / p95 ms): tasks 85/106, messages 46/56, keyword filter 42/49, client-pending 74/87, progress 40/47, health 41/47,
risks 173/206, timeline 244/313, executive 310/358, search 270/511. Before: progress 340 p50, risks 1282 p50, first search p95 6.7 s (lazy keyword index built on the first request) - fixed by
reading the large explanation column only on request, capping risks at the top 200, and warming the keyword index when messages are indexed.
Not measured: more than 10 concurrent clients, sustained load, multi-node, network latency.

## 4. Robustness / security findings
- **ReDoS-style quadratic regex in the parser** (found by the new hostile-input tests): a 200 KB whitespace-only message took 100+ s because of `\s*<This message was edited>\s*$`. Replaced with `endswith`.
  The hostile-input suite now covers 200 KB words/whitespace, repeated trigger phrases, 5k nested parentheses, date-like spam, random Unicode/NUL bytes, 2,000 senders, 5,000 identical messages, CRLF, header lookalikes.
- **Non-UTF8 database silently broke imports** (my embedded Postgres defaulted to WIN1252; the first emoji aborted the job). The backend now refuses to start unless `server_encoding` is UTF8.
- Dependency audit: frontend 0 vulnerabilities; backend 3 high, all one chain (`prisma` CLI -> `@prisma/config` -> `deepmerge-ts` stack exhaustion on recursive objects) in the migration/CLI tool that only reads our own schema, no fix without a Prisma major downgrade/upgrade;
  Python: only pip/setuptools tooling flagged (not runtime); torch could not be audited by pip-audit.
- A cleanup mistake of mine: I stopped my test servers with broad process-name patterns and also ended unrelated shells/node processes; the other project's dev server was unaffected. Cleanup now targets exact ports/PIDs.

## 5. Not done / known gaps
- No accuracy figures on **real** project chats (none supplied); no training-based comparison (Phase 3/4 results remain synthetic-only).
- 1M-message projects; sustained/concurrent load testing; browser end-to-end suite (Playwright); accessibility audit; light-theme and wide-desktop visual checks.
- The AI-engine Docker image build was interrupted when Docker Desktop's engine crashed (the backend image built); compose file validated but the full stack has not been brought up in containers.
- Health/risk weights are still uncalibrated defaults.
