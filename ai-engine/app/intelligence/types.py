"""Shared types. Every derived object carries confidence + evidence + model_version."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

ENGINE_VERSION = "rules_v0.1"


@dataclass
class Msg:
    id: str
    ts: datetime
    sender: Optional[str]
    text: str
    index: int = 0
    category: Optional[str] = None      # from classifier (optional)
    cat_conf: float = 0.0

    @classmethod
    def from_parsed(cls, m) -> "Msg":
        return cls(id=m.message_id, ts=m.timestamp, sender=m.sender_name, text=m.text, index=m.index)


@dataclass
class Evidence:
    message_id: str
    signal: str
    weight: float = 1.0


@dataclass
class Deadline:
    text: str
    when: Optional[datetime]
    confidence: float


@dataclass
class Task:
    id: str
    title: str
    topic: frozenset
    assignee: Optional[str]
    created_by: Optional[str]
    source_message_id: str
    created_at: datetime
    deadline: Optional[Deadline] = None
    status: str = "TODO"
    external_dependency: Optional[str] = None
    completed_at: Optional[datetime] = None
    confidence: float = 0.5
    needs_review: bool = False
    review_reasons: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    status_trace: list[dict] = field(default_factory=list)
    last_touch: Optional[datetime] = None
    model_version: str = ENGINE_VERSION

    def source_ids(self) -> list[str]:
        seen, out = set(), []
        for e in [Evidence(self.source_message_id, "created")] + self.evidence:
            if e.message_id not in seen:
                seen.add(e.message_id)
                out.append(e.message_id)
        return out
