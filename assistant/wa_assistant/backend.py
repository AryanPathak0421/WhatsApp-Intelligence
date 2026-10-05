"""HTTP client for the application backend. Every call carries the signed-in USER's token: the assistant has no identity or rights of its own,
so the backend's role matrix and project-membership checks apply to it exactly as to the user (and answer 404 for projects the user cannot see).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import httpx


@dataclass
class BackendResponse:
    status: int
    data: Any = None
    error_code: Optional[str] = None
    message: Optional[str] = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


class BackendClient:
    def __init__(self, base_url: str, transport: Optional[httpx.AsyncBaseTransport] = None, timeout_s: float = 60.0):
        self._http = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout_s, transport=transport)

    async def aclose(self):
        await self._http.aclose()

    async def request(self, method: str, path: str, token: str, *, params: Optional[dict] = None, json: Optional[dict] = None) -> BackendResponse:
        try:
            r = await self._http.request(method, path, params=params, json=json, headers={"Authorization": f"Bearer {token}"} if token else None)
        except httpx.TimeoutException:
            return BackendResponse(504, error_code="TIMEOUT", message="The application did not answer in time.")
        except httpx.HTTPError:
            return BackendResponse(503, error_code="UNREACHABLE", message="The application backend is not reachable.")
        data = None
        if r.content:
            try:
                data = r.json()
            except ValueError:
                data = None
        if r.is_success:
            return BackendResponse(r.status_code, data)
        err = (data or {}).get("error", {}) if isinstance(data, dict) else {}
        return BackendResponse(r.status_code, None, err.get("code"), err.get("message"))
