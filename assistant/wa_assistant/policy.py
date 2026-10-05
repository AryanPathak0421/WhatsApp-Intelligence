"""Deterministic policy engine. The model PROPOSES a tool call; this code decides. Nothing here is a prompt.

Order of checks for every proposed call:
  1 the tool exists and is offered   2 T3 -> refuse   3 arguments valid (typed, no extras)   4 ids were seen earlier in this session
  5 write rate limit                 6 tier -> allow / confirm      7 taint: a write after untrusted text entered the turn needs confirmation
Authorization itself (role matrix, project membership) is enforced by the backend because every call carries the user's own token.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from pydantic import ValidationError

from .config import Settings
from .session import Session
from .tools.registry import Tier, Tool


class Decision(str, Enum):
    ALLOW = "allow"
    CONFIRM = "confirm"
    REFUSE = "refuse"
    INVALID = "invalid"


@dataclass
class Verdict:
    decision: Decision
    reason: str = ""
    tool: Optional[Tool] = None
    args: dict = field(default_factory=dict)
    preview: str = ""
    tainted: bool = False


def _errors(e: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(x) for x in err['loc']) or 'arguments'}: {err['msg']}" for err in e.errors()[:6])


class PolicyEngine:
    def __init__(self, registry: dict[str, Tool], settings: Settings):
        self.registry, self.settings = registry, settings

    def offered(self) -> list[Tool]:
        """Tools shown to the model. T3 tools are not offered; a model that names one anyway gets a refusal, not an error."""
        return [t for t in self.registry.values() if t.tier != Tier.T3]

    def evaluate(self, session: Session, name: str, raw_args: dict, *, confirmed: bool = False) -> Verdict:
        tool = self.registry.get(name)
        if tool is None:
            return Verdict(Decision.INVALID, f"Unknown tool '{name}'. Available: {', '.join(t.name for t in self.offered())}.")
        if tool.tier == Tier.T3:
            return Verdict(Decision.REFUSE, tool.refusal, tool)
        if "__invalid_json__" in raw_args:
            return Verdict(Decision.INVALID, "The tool arguments were not valid JSON.", tool)
        try:
            args = tool.args.model_validate(raw_args).model_dump(exclude_none=True)
        except ValidationError as e:
            return Verdict(Decision.INVALID, _errors(e), tool)
        for arg, kind in tool.id_args.items():
            if arg in args and not session.knows(kind, args[arg]):
                return Verdict(Decision.INVALID, f"{arg} '{args[arg]}' was not returned by any earlier lookup in this conversation. "
                                                  f"Call the matching list tool first and use an id it returned.", tool)
        is_write = tool.tier in (Tier.T1, Tier.T2)
        if is_write and session.count_recent(session.write_times) >= self.settings.writes_per_minute:
            return Verdict(Decision.REFUSE, "Too many changes in the last minute; wait a moment and try again.", tool)
        preview = tool.preview(args) if tool.preview else tool.description
        if confirmed or not is_write:
            return Verdict(Decision.ALLOW, "", tool, args, preview, session.turn_tainted)
        if tool.tier == Tier.T2:
            return Verdict(Decision.CONFIRM, "This action needs your confirmation.", tool, args, preview, session.turn_tainted)
        if session.turn_tainted and self.settings.taint_requires_confirmation:
            return Verdict(Decision.CONFIRM, "This change follows text from a document or chat, so it needs your confirmation.", tool, args, preview, True)
        return Verdict(Decision.ALLOW, "", tool, args, preview, False)
