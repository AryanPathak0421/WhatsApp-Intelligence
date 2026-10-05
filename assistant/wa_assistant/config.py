"""Runtime settings, read from the environment once. No secrets are defaulted."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


@dataclass(frozen=True)
class Settings:
    backend_url: str = field(default_factory=lambda: os.getenv("BACKEND_URL", "http://localhost:4000/api"))
    llm_base_url: str = field(default_factory=lambda: os.getenv("LLM_BASE_URL", "http://localhost:8080/v1"))  # llama.cpp / Ollama / vLLM
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "local"))
    llm_timeout_s: int = field(default_factory=lambda: _int("LLM_TIMEOUT_S", 300))     # CPU inference is slow
    max_steps: int = field(default_factory=lambda: _int("ASSISTANT_MAX_STEPS", 6))
    max_invalid_retries: int = field(default_factory=lambda: _int("ASSISTANT_MAX_INVALID_RETRIES", 2))
    pending_ttl_s: int = field(default_factory=lambda: _int("PENDING_TTL_S", 300))
    writes_per_minute: int = field(default_factory=lambda: _int("ASSISTANT_WRITES_PER_MIN", 10))
    messages_per_minute: int = field(default_factory=lambda: _int("ASSISTANT_MESSAGES_PER_MIN", 30))
    session_ttl_s: int = field(default_factory=lambda: _int("SESSION_TTL_S", 3600))
    history_messages: int = field(default_factory=lambda: _int("ASSISTANT_HISTORY", 20))
    audit_file: str = field(default_factory=lambda: os.getenv("ASSISTANT_AUDIT_FILE", "audit.jsonl"))
    feedback_file: str = field(default_factory=lambda: os.getenv("ASSISTANT_FEEDBACK_FILE", "feedback.jsonl"))
    docs_dir: str = field(default_factory=lambda: os.getenv("ASSISTANT_DOCS_DIR", "docs_store"))
    # after untrusted text (documents, chat-derived titles) entered the context, writes in that turn need confirmation
    taint_requires_confirmation: bool = field(default_factory=lambda: os.getenv("TAINT_REQUIRES_CONFIRMATION", "true").lower() != "false")
    abstain_below: float = field(default_factory=lambda: float(os.getenv("RAG_ABSTAIN_BELOW", "0.2")))
