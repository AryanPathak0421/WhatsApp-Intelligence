"""Deterministic LLM doubles for tests and for evaluating the *safety layers* independently of any model.

ScriptedLLM    replays a fixed list of outputs.
ObedientLLM    a worst-case model: it does whatever instruction appears in the latest tool result ("CALL: tool {json}") or user turn.
               If the defences hold against this model, a real model that gets hijacked cannot do more.
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Callable, Optional

from .base import LLMOutput, ToolCall

_CALL = re.compile(r"CALL:\s*([a-z_]+)\s*(\{.*?\})", re.S)


def call(name: str, /, **arguments) -> ToolCall:
    return ToolCall(id=f"call_{uuid.uuid4().hex[:8]}", name=name, arguments=arguments)


def _readable(text: str) -> str:
    """All string values inside a JSON tool result, unescaped, joined; falls back to the raw text."""
    try:
        doc = json.loads(text)
    except ValueError:
        return text
    out = []

    def walk(x):
        if isinstance(x, str):
            out.append(x.replace('\\"', '"'))
            try:
                walk(json.loads(x))
            except ValueError:
                pass
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(doc)
    return "\n".join(out)


class ScriptedLLM:
    name = "scripted"

    def __init__(self, outputs: list[LLMOutput | Callable[[list[dict]], LLMOutput]]):
        self.outputs, self.calls = list(outputs), []

    async def complete(self, messages, tools=None, *, max_tokens=700) -> LLMOutput:
        self.calls.append({"messages": messages, "tools": [t["function"]["name"] for t in tools or []]})
        if not self.outputs:
            return LLMOutput(text="(script exhausted)")
        o = self.outputs.pop(0)
        return o(messages) if callable(o) else o


class ObedientLLM:
    name = "obedient-worst-case"

    async def complete(self, messages, tools=None, *, max_tokens=700) -> LLMOutput:
        last = messages[-1]
        text = last.get("content") or ""
        if isinstance(text, list):
            text = " ".join(str(p) for p in text)
        m = _CALL.search(_readable(text))      # tool results are JSON-escaped (twice for wrapped data); a real model reads through that
        if m and last["role"] in ("tool", "user"):
            try:
                args = json.loads(m.group(2))
            except ValueError:
                args = {}
            return LLMOutput(tool_calls=[ToolCall(id=f"call_{uuid.uuid4().hex[:8]}", name=m.group(1), arguments=args)])
        return LLMOutput(text="Okay.")


class ThenObedient(ScriptedLLM):
    """Scripted prefix (to set up the conversation), then the worst-case obedient model for every later step."""
    name = "scripted-then-obedient"

    async def complete(self, messages, tools=None, *, max_tokens=700) -> LLMOutput:
        if self.outputs:
            return await super().complete(messages, tools, max_tokens=max_tokens)
        return await ObedientLLM().complete(messages, tools, max_tokens=max_tokens)
