"""LLM interface. The agent only depends on this; any OpenAI-compatible server (llama.cpp, Ollama, vLLM) or a scripted test double fits."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict                      # {"__invalid_json__": raw} when the model produced unparsable arguments


@dataclass
class LLMOutput:
    text: Optional[str] = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    latency_ms: float = 0.0
    usage: dict = field(default_factory=dict)


class LLMClient(Protocol):
    name: str

    async def complete(self, messages: list[dict], tools: Optional[list[dict]] = None, *, max_tokens: int = 700) -> LLMOutput: ...
