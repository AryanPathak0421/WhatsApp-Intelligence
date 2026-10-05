"""Annotation schema, append-only store and active-learning triage."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.labels import AUTO_ACCEPT, CATEGORIES, ENTITY_TYPES, REVIEW_MIN, TASK_STATUSES, canonical


class EntitySpan(BaseModel):
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    label: str
    text: str

    @field_validator("label")
    @classmethod
    def _label(cls, v):
        if v not in ENTITY_TYPES:
            raise ValueError(f"unknown entity type {v}")
        return v


class AnnotationIn(BaseModel):
    project_id: str
    message_id: str
    message: str                      # original text (never modified)
    category: str
    entities: list[EntitySpan] = []
    intent: Optional[str] = None
    status: Optional[str] = None
    assignee: Optional[str] = None
    deadline_text: Optional[str] = None
    task_key: Optional[str] = None    # annotator-defined id to link messages of one task
    client_pending: bool = False
    risk: bool = False
    conflict_with: Optional[str] = None   # message_id of the contradicting message
    reviewer: str
    split_hint: Optional[Literal["train", "val", "test"]] = None
    proposal: Optional[dict] = None          # the pre-label shown to the annotator (kept as model_prediction to measure proposal quality)

    @field_validator("category")
    @classmethod
    def _cat(cls, v):
        if v not in CATEGORIES:
            raise ValueError(f"unknown category {v}")
        return canonical(v)

    @field_validator("status")
    @classmethod
    def _status(cls, v):
        if v is not None and v not in TASK_STATUSES:
            raise ValueError(f"unknown status {v}")
        return v


def _canon(r: dict) -> dict:
    """Records written before a label was merged still read back under the canonical name (both the human label and the proposal)."""
    r["category"] = canonical(r["category"])
    if isinstance(r.get("model_prediction"), dict) and r["model_prediction"].get("category"):
        r["model_prediction"] = {**r["model_prediction"], "category": canonical(r["model_prediction"]["category"])}
    return r


class AnnotationStore:
    """Append-only JSONL. Latest record per (project_id, message_id) wins, but the
    full history is kept for audit and for training on corrections."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def save(self, a: AnnotationIn, model_prediction: Optional[dict] = None) -> dict:
        rec = a.model_dump(exclude={"proposal"})
        model_prediction = model_prediction or a.proposal
        rec.update(confidence=1.0, source="human",
                   annotated_at=datetime.now(timezone.utc).isoformat(),
                   model_prediction=model_prediction)  # keeps what the model said (for correction analysis)
        with self._lock, self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec

    def history(self) -> list[dict]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as fh:
            return [_canon(json.loads(line)) for line in fh if line.strip()]

    def latest(self) -> dict[tuple[str, str], dict]:
        out = {}
        for r in self.history():
            out[(r["project_id"], r["message_id"])] = r
        return out

    def latest_by(self, reviewer: str, project_id: Optional[str] = None) -> list[dict]:
        """Latest label per message from ONE reviewer (needed for double annotation / kappa: `latest()` keeps only the last writer)."""
        out = {}
        for r in self.history():
            if r["reviewer"] == reviewer and project_id in (None, r["project_id"]):
                out[(r["project_id"], r["message_id"])] = r
        return list(out.values())

    def export_training(self, path: str | Path) -> int:
        rows = list(self.latest().values())
        with Path(path).open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        return len(rows)


def triage(confidence: float) -> Literal["auto_accept", "review", "annotate"]:
    """Spec: >95% accept; 70-95% flag for review; <70% annotation queue."""
    if confidence > AUTO_ACCEPT:
        return "auto_accept"
    if confidence >= REVIEW_MIN:
        return "review"
    return "annotate"


def build_queue(predictions: list[dict], already_labelled: set[tuple[str, str]],
                limit: int = 200) -> list[dict]:
    """Uncertainty sampling: lowest-confidence first, skipping labelled messages.

    Each prediction needs project_id, message_id, confidence (+ optional runner-up
    margin). Messages that the model auto-accepts are excluded.
    """
    todo = [p for p in predictions
            if (p["project_id"], p["message_id"]) not in already_labelled
            and triage(p["confidence"]) != "auto_accept"]
    todo.sort(key=lambda p: (p["confidence"], p.get("margin", 1.0)))
    return [{**p, "queue": triage(p["confidence"])} for p in todo[:limit]]
