"""Client for a self-hosted OpenAI-compatible chat-completions server (llama.cpp `llama-server`, Ollama, vLLM).

Nothing here talks to an external provider: `base_url` must point at a server you run. Tool arguments the model produces are untrusted
input; they are parsed here but validated by the policy engine, never executed from here.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Optional

import httpx

from .base import LLMOutput, ToolCall


class OpenAICompatClient:
    def __init__(self, base_url: str, model: str, timeout_s: int = 300, transport: Optional[httpx.AsyncBaseTransport] = None,
                 temperature: float = 0.0):
        self.name = f"openai-compat:{model}"
        self.model, self.temperature = model, temperature
        self._http = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout_s, transport=transport)

    async def aclose(self):
        await self._http.aclose()

    async def complete(self, messages, tools=None, *, max_tokens=700) -> LLMOutput:
        body = {"model": self.model, "messages": messages, "temperature": self.temperature, "max_tokens": max_tokens}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        t0 = time.perf_counter()
        r = await self._http.post("/chat/completions", json=body)
        r.raise_for_status()
        data = r.json()
        msg = (data.get("choices") or [{}])[0].get("message") or {}
        calls = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            raw = fn.get("arguments", "{}")
            try:
                args = json.loads(raw) if isinstance(raw, str) else dict(raw)
                if not isinstance(args, dict):
                    args = {"__invalid_json__": raw}
            except (ValueError, TypeError):
                args = {"__invalid_json__": str(raw)[:300]}
            calls.append(ToolCall(id=tc.get("id") or f"call_{uuid.uuid4().hex[:8]}", name=fn.get("name", ""), arguments=args))
        return LLMOutput(text=msg.get("content") or None, tool_calls=calls, latency_ms=(time.perf_counter() - t0) * 1000,
                         usage=data.get("usage") or {})
