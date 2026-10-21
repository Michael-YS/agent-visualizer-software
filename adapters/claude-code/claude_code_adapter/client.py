from __future__ import annotations

from typing import Any

import httpx


class BridgeUnavailable(RuntimeError):
    pass


class BridgeClient:
    def __init__(self, base_url: str, timeout: float) -> None:
        self.url = f"{base_url.rstrip('/')}/v1/agents/state"
        self.client = httpx.AsyncClient(timeout=timeout)

    async def publish(self, payload: dict[str, Any]) -> None:
        try:
            response = await self.client.post(self.url, json=payload)
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise BridgeUnavailable(str(error)) from error

    async def close(self) -> None:
        await self.client.aclose()
