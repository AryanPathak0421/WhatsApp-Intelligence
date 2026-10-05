"""Wiring: one place that assembles the agent from its parts (used by the API, the tests and the evaluation harness)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .agent import Agent
from .audit import AuditLog
from .backend import BackendClient
from .config import Settings
from .executor import ToolExecutor
from .llm.base import LLMClient
from .pending import PendingStore
from .policy import PolicyEngine
from .rag.store import DocumentStore
from .session import SessionStore
from .tools.registry import build_registry


@dataclass
class Assistant:
    agent: Agent
    sessions: SessionStore
    pending: PendingStore
    audit: AuditLog
    backend: BackendClient
    documents: Optional[DocumentStore]
    settings: Settings


def build_assistant(llm: LLMClient, backend: BackendClient, settings: Optional[Settings] = None, documents: Optional[DocumentStore] = None,
                    audit_path: Optional[str] = None) -> Assistant:
    s = settings or Settings()
    registry = build_registry()
    audit = AuditLog(audit_path or s.audit_file)
    pending = PendingStore(s.pending_ttl_s)
    agent = Agent(llm, PolicyEngine(registry, s), ToolExecutor(backend, documents), pending, audit, s)
    return Assistant(agent, SessionStore(s.session_ttl_s), pending, audit, backend, documents, s)
