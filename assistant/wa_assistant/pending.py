"""Pending sensitive actions (tier T2) and their confirmation.

A confirmation executes exactly what was previewed: the stored hash of (user, tool, arguments) is recomputed at confirm time, it expires,
it can be consumed once, and only the user who was shown it can confirm. Confirming is a separate API call made by the UI button, so text
inside a document or a chat message cannot confirm anything.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from .audit import args_hash


class PendingError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass
class PendingAction:
    id: str
    user_id: str
    session_id: str
    tool: str
    args: dict
    preview: str
    digest: str
    tainted: bool
    created: float
    expires: float
    status: str = "pending"                 # pending | confirmed | cancelled | expired


class PendingStore:
    def __init__(self, ttl_s: int = 300):
        self.ttl_s, self._items, self._lock = ttl_s, {}, threading.Lock()

    def create(self, user_id: str, session_id: str, tool: str, args: dict, preview: str, tainted: bool = False) -> PendingAction:
        now = time.time()
        p = PendingAction(id=uuid.uuid4().hex[:12], user_id=user_id, session_id=session_id, tool=tool, args=dict(args), preview=preview,
                          digest=args_hash(tool, args, user_id), tainted=tainted, created=now, expires=now + self.ttl_s)
        with self._lock:
            self._items[p.id] = p
        return p

    def _get(self, pid: str, user_id: str) -> PendingAction:
        p = self._items.get(pid)
        if p is None or p.user_id != user_id:        # not yours = does not exist
            raise PendingError("PENDING_NOT_FOUND", "No such pending action.")
        if p.status == "pending" and time.time() > p.expires:
            p.status = "expired"
        return p

    def take_for_confirmation(self, pid: str, user_id: str) -> PendingAction:
        """Atomically mark confirmed (single use). Raises if expired, already used, cancelled or tampered."""
        with self._lock:
            p = self._get(pid, user_id)
            if p.status != "pending":
                raise PendingError("PENDING_" + p.status.upper(), f"This action is {p.status}.")
            if args_hash(p.tool, p.args, p.user_id) != p.digest:
                raise PendingError("PENDING_TAMPERED", "The stored action no longer matches what was shown to you.")
            p.status = "confirmed"
            return p

    def cancel(self, pid: str, user_id: str) -> PendingAction:
        with self._lock:
            p = self._get(pid, user_id)
            if p.status == "pending":
                p.status = "cancelled"
            return p

    def list_pending(self, user_id: str, session_id: Optional[str] = None) -> list[PendingAction]:
        with self._lock:
            out = []
            for p in self._items.values():
                if p.user_id == user_id and (session_id in (None, p.session_id)):
                    self._get(p.id, user_id)
                    if p.status == "pending":
                        out.append(p)
            return out
