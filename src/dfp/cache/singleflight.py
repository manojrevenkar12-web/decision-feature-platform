"""Request coalescing: concurrent misses for the same key share one provider call.

A double-submitted application fires the same decision flow twice within milliseconds; without this
both pay for a bureau pull.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar, cast

T = TypeVar("T")


class SingleFlight:
    def __init__(self) -> None:
        self._inflight: dict[str, asyncio.Future[Any]] = {}
        self.shared = 0

    async def do(self, key: str, fn: Callable[[], Awaitable[T]]) -> T:
        fut = self._inflight.get(key)
        if fut is not None:
            self.shared += 1
            return cast(T, await asyncio.shield(fut))
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._inflight[key] = fut
        try:
            result = await fn()
            fut.set_result(result)
            return result
        except BaseException as e:
            fut.set_exception(e)
            fut.exception()  # mark retrieved for callers that never awaited
            raise
        finally:
            del self._inflight[key]
