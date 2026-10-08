# Documentation (`docx/`)

One folder per area. Every document says what exists, how it works, how to run or test it, and what it does **not** do. Numbers are measured or marked as unmeasured.
Older phase documents (parsing, benchmarks, backend, frontend, deployment) are still in [`../docs/`](../docs/); this folder is the structured, current set.

| Folder | Read this for | Main documents |
|---|---|---|
| [00-overview](00-overview/) | the whole system on one page, status of every part | [PROJECT_OVERVIEW](00-overview/PROJECT_OVERVIEW.md), [10-page architecture PDF](00-overview/WhatsApp_Platform_Architecture.pdf) (rebuild: `build_architecture_pdf.py`) |
| [01-analysis](01-analysis/) | existing-system analysis, WhatsApp feasibility, gaps, decisions | [PHASE1_ANALYSIS_AND_GAP](01-analysis/PHASE1_ANALYSIS_AND_GAP.md), [DECISIONS](01-analysis/DECISIONS.md) |
| [02-architecture](02-architecture/) | services, data flow, schema additions, every HTTP endpoint | [ARCHITECTURE](02-architecture/ARCHITECTURE.md), [API_REFERENCE](02-architecture/API_REFERENCE.md) |
| [03-ingestion](03-ingestion/) | getting messages in: watched-folder import of exports, and the WhatsApp Cloud API webhook | [WATCHED_FOLDER_IMPORT](03-ingestion/WATCHED_FOLDER_IMPORT.md), [WHATSAPP_INGESTION](03-ingestion/WHATSAPP_INGESTION.md) |
| [04-queue-and-events](04-queue-and-events/) | BullMQ jobs, debounced re-analysis, live (SSE) events | [QUEUE_AND_EVENTS](04-queue-and-events/QUEUE_AND_EVENTS.md) |
| [05-ai-nlp-pipeline](05-ai-nlp-pipeline/) | question/answer analytics, sentiment, periodic summaries, project-completion rule, reliability labels and task-title quality | [QA_ANALYTICS](05-ai-nlp-pipeline/QA_ANALYTICS.md), [SENTIMENT](05-ai-nlp-pipeline/SENTIMENT.md), [PERIODIC_SUMMARIES](05-ai-nlp-pipeline/PERIODIC_SUMMARIES.md), [PROJECT_COMPLETION_RULE](05-ai-nlp-pipeline/PROJECT_COMPLETION_RULE.md), [RELIABILITY_AND_TASK_QUALITY](05-ai-nlp-pipeline/RELIABILITY_AND_TASK_QUALITY.md) |
| [06-rag-and-search](06-rag-and-search/) | project message search and the document/paper RAG with citations | [RAG_AND_SEARCH](06-rag-and-search/RAG_AND_SEARCH.md) |
| [07-assistant](07-assistant/) | the tool-using assistant: design, literature, implementation, policy | [ASSISTANT_IMPLEMENTATION](07-assistant/ASSISTANT_IMPLEMENTATION.md), [ARCHITECTURE_AND_LITERATURE](07-assistant/ARCHITECTURE_AND_LITERATURE.md) |
| [08-voice](08-voice/) | microphone/voice pipeline | [VOICE](08-voice/VOICE.md) |
| [09-security-and-privacy](09-security-and-privacy/) | threat model with implemented controls; retention and erasure | [SECURITY](09-security-and-privacy/SECURITY.md), [PRIVACY_AND_RETENTION](09-security-and-privacy/PRIVACY_AND_RETENTION.md) |
| [10-evaluation](10-evaluation/) | every test suite, benchmark and measured result | [EVALUATION](10-evaluation/EVALUATION.md) |
| [11-deployment-and-ops](11-deployment-and-ops/) | running the stack, ports, config, health checks, runbooks | [OPERATIONS](11-deployment-and-ops/OPERATIONS.md) |
| [12-datasets-and-models](12-datasets-and-models/) | labelled data, classifier results, the downloaded LLM and its licence | [DATASETS_AND_MODELS](12-datasets-and-models/DATASETS_AND_MODELS.md) |

Conventions: Markdown only (export to .docx/.pdf with any converter if a Word file is needed). A feature is "Done" only if it has tests; measured numbers state what they were measured on.
