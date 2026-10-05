"""Per-user conversation state. A session is bound to the user the backend authenticated; it can never be used by another user."""
from __future__ import annotations

import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Session:
    id: str
    user_id: str
    role: str
    token: str                                     # the USER's access token: every tool call is made with it
    messages: list[dict] = field(default_factory=list)
    known_ids: dict[str, set] = field(default_factory=lambda: {"project": set(), "task": set(), "user": set()})
    task_project: dict[str, str] = field(default_factory=dict)   # task id -> project id (for independent read-back verification)
    write_times: deque = field(default_factory=lambda: deque(maxlen=200))
    message_times: deque = field(default_factory=lambda: deque(maxlen=200))
    last_search: list[dict] = field(default_factory=list)   # chunks retrieved this conversation (for citation checks)
    turn_tainted: bool = False                     # untrusted text entered the context during the current turn
    created: float = field(default_factory=time.time)
    touched: float = field(default_factory=time.time)

    def remember_id(self, kind: str, value: str) -> None:
        self.known_ids.setdefault(kind, set()).add(str(value))

    def knows(self, kind: str, value: str) -> bool:
        return str(value) in self.known_ids.get(kind, set())

    def count_recent(self, dq: deque, window_s: int = 60) -> int:
        cutoff = time.time() - window_s
        return sum(1 for t in dq if t >= cutoff)


class SessionStore:
    def __init__(self, ttl_s: int = 3600):
        self.ttl_s, self._items = ttl_s, {}

    def get_or_create(self, session_id: Optional[str], user_id: str, role: str, token: str) -> Session:
        self._sweep()
        s = self._items.get(session_id) if session_id else None
        if s is not None:
            if s.user_id != user_id:                   # someone else's session id: behave as if it did not exist
                s = None
            else:
                s.token, s.role, s.touched = token, role, time.time()   # tokens rotate; permissions are re-read each request
                return s
        s = Session(id=uuid.uuid4().hex, user_id=user_id, role=role, token=token)
        self._items[s.id] = s
        return s

    def get(self, session_id: str, user_id: str) -> Optional[Session]:
        s = self._items.get(session_id)
        return s if s and s.user_id == user_id else None

    def _sweep(self):
        cutoff = time.time() - self.ttl_s
        for k in [k for k, v in self._items.items() if v.touched < cutoff]:
            del self._items[k]
