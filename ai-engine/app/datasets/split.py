"""Project-level train/val/test split (never split messages of one project)."""
from __future__ import annotations

import hashlib
from collections import defaultdict


def _bucket(project_id: str, salt: str) -> float:
    h = hashlib.sha256(f"{salt}:{project_id}".encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def split_projects(project_ids: list[str], val: float = 0.2, test: float = 0.2,
                   salt: str = "v1", allow_test: bool = True) -> dict[str, str]:
    """Deterministic assignment by hashed project id (stable as data grows).

    ``allow_test=False`` is used for synthetic data: it is routed to train/val only.
    """
    out = {}
    for pid in sorted(set(project_ids)):
        b = _bucket(pid, salt)
        if allow_test and b < test:
            out[pid] = "test"
        elif b < (test if allow_test else 0) + val:
            out[pid] = "val"
        else:
            out[pid] = "train"
    return out


def split_records(records: list[dict], **kw) -> dict[str, list[dict]]:
    assign = split_projects([r["project_id"] for r in records], **kw)
    parts: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        parts[assign[r["project_id"]]].append(r)
    return dict(parts)
