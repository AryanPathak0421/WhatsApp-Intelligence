# Real-data labelling plan (the single most valuable next step)

Goal: replace guesses with measurements. After this, every accuracy claim, every threshold and every model comparison in the docs can be redone on real data.

## 1. What to collect
- **20-30 real project chats** (different clients, teams and project types; mix of English, Hinglish and Hindi), 1,000-5,000 messages each is plenty. More projects beat more messages from the same project.
- Include messy ones: long silences, scope changes, disputes, voice-note-heavy groups. Do not cherry-pick the clean projects, or the numbers will lie.
- Export from WhatsApp **without media**. Keep the exact original `.txt` files (private, encrypted storage).

## 2. Privacy first
- Get the owner's/client's permission per your policy; chats contain third-party personal data.
- Run `python -m app.datasets.anonymize chat.txt chat.anon.txt --map chat.names.json`: senders become Person A/B/..., name parts, phones, e-mails, URLs and long digit strings are masked, system messages are blanked. Role hints in sender names survive (`Person C (Sales)`).
- The tool cannot catch everything (company names, addresses, odd spellings): **a person must skim each anonymised file** before it goes to annotators. Keep the mapping file with the data owner only.
- Annotators work on the anonymised copy, inside your network (`/annotate` is served by the AI engine; expose it only through the authenticated backend/VPN).

## 3. Who labels
- 2 annotators who know software projects (a PM and a developer is ideal), plus 1 adjudicator.
- ~60 minutes of guideline training on the 24 categories with examples drawn from the unseen set (`ai-engine/eval/unseen/`).
- **Double-annotate 10%** of every project (randomly chosen messages). Compute `python -m app.evaluation.agreement a.jsonl b.jsonl`. kappa >= 0.7 -> go on; 0.6-0.7 -> fix the guidelines, relabel; < 0.6 -> stop.

## 4. Labelling guidelines (short form - extend with your disputes)
- **Label what the message itself does**, using context only to disambiguate ("Done" after "Payment API?" is TASK_COMPLETED for the payment task).
- Status words need a subject: "ready" is not "completed"; "tested successfully" is TESTING; "deployed" is DEPLOYMENT. When unsure between two, choose the weaker one and tick **needs review**.
- CLIENT_PENDING = the team is waiting on the client (including named clients: "Mr Kapoor hasn't sent the logo"). Resolve it by labelling the client's reply CLIENT_APPROVAL / the providing message and linking via `task_key`.
- Requests addressed to a *client* are not developer tasks.
- A requirement change needs an old and a new value in the notes field when you can tell.
- Link every message of one task with the same `task_key` (this is what trains and tests task resolution).
- Gold facts per project (3 minutes each, in `eval/unseen/<name>.gold.json` format): the tasks with assignee and final status, client-pending items with final state, requirement changes, bugs with final state, decisions, contradictions. This is what the end-to-end benchmark scores.

## 5. Targets and how the data is used
| Item | Target |
|---|---|
| labelled messages | >= 5,000, >= 100 of each rare class (BLOCKER, BUG_FIXED, REQUIREMENT_CHANGE, CLIENT_APPROVAL ...) - the annotation queue (lowest confidence first) fills gaps efficiently |
| projects | 20-30; 60% train / 20% validation / **20% frozen test**, split by project (`app/datasets/split.py`) |
| end-to-end gold files | >= 10 projects, kept untouched until a model/rules version is ready to be scored |
| agreement | kappa >= 0.7 on the double-annotated 10% |

Then: re-run `train_baseline` (REAL_TEST appears), `finetune_transformer`, `bench/unseen_eval`, the registry gate (`docs/MODEL_LIFECYCLE.md`), and replace the "estimate" sentences in the docs with the measured numbers.

## 6. Time/cost estimate (rough, for planning)
~5,000 messages x ~10 s each = ~14 annotator-hours, plus ~3 h agreement checking, ~8 h gold files, ~4 h anonymisation/review: about 4-5 person-days spread over two annotators. Active learning reduces the labelling needed once a first model exists.

## 7. The pre-labelling workflow (implemented)
```bash
cd ai-engine
# 1. anonymise (masks names, phones, e-mails, URLs, @mentions, pasted API keys/passwords; add --redact "Company Ltd=ClientCo" --role "Person B=Client")
python -m app.datasets.anonymize ../private-data/raw/<chat>.txt ../private-data/anon/<chat>.anon.txt --map ../private-data/anon/<chat>.names.json
# 2. propose labels (rules + task linking + auto-detected roles; override a role with --role "Person H=CLIENT")
python -m app.annotation.prelabel ../private-data/anon/<chat>.anon.txt ../private-data/batches/<chat>.batch.json --project <name>
# 3. label: keep labels in the private folder
ANNOTATION_FILE=../private-data/annotations/annotations.jsonl python -m uvicorn app.api.main:app --port 8000     # open http://localhost:8000/annotate
```
In `/annotate`: enter your name, load the `.batch.json`, correct each proposal (Ctrl+Enter saves and moves on). Items marked **double** go to a second annotator who ticks **blind** (proposals hidden, so the labels are independent).
Afterwards: `GET /ai/annotation/export?reviewer=<name>` for each annotator -> save as files -> `python -m app.evaluation.agreement a.jsonl b.jsonl`; `GET /ai/annotation/stats` shows how often the proposals were accepted overall, per category and per confidence band (this is the first real measurement of the rules).
Proposals are suggestions: nothing is a label until a person saves it, and the proposal that was shown is stored next to the human label so corrections can be analysed and reused as training data.
