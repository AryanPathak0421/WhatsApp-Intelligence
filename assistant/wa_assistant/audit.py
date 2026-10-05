"""Append-only audit trail: who asked for what, what the policy decided, what the backend did, whether it was verified.

Message text and tool *results* are not logged (they can contain client data). Tool arguments are, with long free text truncated,
because the arguments are the action. A hash of the full arguments is stored so a confirmation can be matched to what was shown.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any, Optional


def args_hash(tool: str, args: dict, user_id: str = "") -> str:
    return hashlib.sha256(json.dumps([user_id, tool, args], sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _clip(v: Any, n: int = 200):
    if isinstance(v, str):
        return v if len(v) <= n else v[:n] + f"...(+{len(v) - n} chars)"
    if isinstance(v, dict):
        return {k: _clip(x, n) for k, x in v.items()}
    if isinstance(v, list):
        return [_clip(x, n) for x in v[:20]]
    return v


class AuditLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def write(self, event: str, *, user_id: str, session_id: str, turn_id: Optional[str] = None, **fields) -> dict:
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()), "event": event, "user_id": user_id, "session_id": session_id,
               "turn_id": turn_id, **{k: _clip(v) for k, v in fields.items()}}
        with self._lock, self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        return rec

    def read(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.open(encoding="utf-8") if line.strip()]
