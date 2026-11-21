"""Coalescing across Lambda containers. `SingleFlight` only merges calls inside one container; a
double-submitted application usually lands on two. The first miss takes a short Redis lease
(SET NX PX); the others poll the cache tiers until the entry appears or the lease lapses, and only
then call the provider themselves."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from dfp.cache.tiers import Entry


class RedisLease:
    def __init__(self, client: Any, lease_ms: int = 2000, poll_ms: int = 25, prefix: str = "dfp:lease:") -> None:
        self.client = client
        self.lease_ms = lease_ms
        self.poll_ms = poll_ms
        self.prefix = prefix
        self.waited = 0

    async def do(self, key: str, read: Callable[[], Entry | None], fetch: Callable[[], Awaitable[Entry]]) -> Entry:
        token = uuid.uuid4().hex
        name = self.prefix + key
        if self.client.set(name, token, nx=True, px=self.lease_ms):
            try:
                return await fetch()
            finally:
                # release only our own lease (compare-and-delete)
                if self.client.get(name) in (token, token.encode()):
                    self.client.delete(name)
        self.waited += 1
        loops = max(1, self.lease_ms // self.poll_ms)
        for _ in range(loops):
            await asyncio.sleep(self.poll_ms / 1000)
            hit = read()
            if hit is not None:
                return hit
            if not self.client.exists(name):
                break
        return await fetch()
