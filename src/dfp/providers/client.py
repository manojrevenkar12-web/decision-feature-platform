"""HTTP clients for data providers, with a timeout, one retry inside the budget and a breaker."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from dfp.providers.breaker import Breaker


class ProviderError(Exception):
    pass


class Provider(Protocol):
    name: str

    async def fetch(self, entity: str) -> dict[str, Any]: ...


@dataclass
class HttpProvider:
    name: str
    base_url: str
    api_key: str
    timeout_s: float = 1.2
    client: httpx.AsyncClient | None = None

    async def fetch(self, entity: str) -> dict[str, Any]:
        client = self.client or httpx.AsyncClient()
        try:
            r = await client.get(
                f"{self.base_url}/v1/{self.name}/{entity}",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout_s,
            )
        except httpx.HTTPError as e:
            raise ProviderError(f"{self.name}: {e}") from e
        finally:
            if self.client is None:
                await client.aclose()
        if r.status_code >= 500 or r.status_code == 429:
            raise ProviderError(f"{self.name}: HTTP {r.status_code}")
        r.raise_for_status()
        data: dict[str, Any] = r.json()
        return data


@dataclass
class Resilient:
    """Wraps a provider: fail fast while the breaker is open, retry once if the budget allows."""

    inner: Provider
    breaker: Breaker = field(default_factory=Breaker)
    retry_once: bool = True
    clock: Any = time.time

    @property
    def name(self) -> str:
        return self.inner.name

    async def fetch(self, entity: str) -> dict[str, Any]:
        attempts = 2 if self.retry_once else 1
        last: Exception | None = None
        for _ in range(attempts):
            if not self.breaker.allow(self.clock()):
                raise ProviderError(f"{self.name}: circuit open")
            try:
                out = await self.inner.fetch(entity)
            except ProviderError as e:
                self.breaker.record(False, self.clock())
                last = e
                continue
            self.breaker.record(True, self.clock())
            return out
        assert last is not None
        raise last
