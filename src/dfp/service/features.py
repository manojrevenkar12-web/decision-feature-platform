"""Serving: the features a decision flow asks for, each with where it came from and how old it is.

Stream features are read from the bucket store with the tile plan of their window. Provider features
go through the multi-level cache, then a coalesced call to the provider; if the provider fails, an
older response is served only where the freshness rule allows stale-if-error, and is marked so.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from dfp.cache.multilevel import MultiLevelCache, cache_key
from dfp.cache.policy import FreshnessPolicy
from dfp.cache.singleflight import SingleFlight
from dfp.cache.tiers import Entry
from dfp.features import tiles
from dfp.features.spec import FeatureSet
from dfp.providers.client import Provider, ProviderError
from dfp.stream.consumer import partition_key
from dfp.stream.store import HOUR, MINUTE, BucketStore


@dataclass(frozen=True)
class FeatureValue:
    name: str
    value: Any
    source: str  # stream | l1 | redis | dynamodb | provider | stale_if_error | missing
    age_s: float | None = None


def stream_value(store: BucketStore, pk: str, feature_window: int, end_minute: int, tile: int) -> tiles.Bucket:
    p = tiles.plan(end_minute, feature_window, tile)
    total = tiles.Bucket()
    for lo, hi in p.minute_ranges:
        for b in store.read(pk, MINUTE, lo, hi):
            total.merge(b)
    if p.hour_range is not None:
        for b in store.read(pk, HOUR, *p.hour_range):
            total.merge(b)
    return total


@dataclass
class FeatureService:
    features: FeatureSet
    store: BucketStore
    cache: MultiLevelCache
    policies: dict[str, FreshnessPolicy]
    providers: dict[str, Provider]
    hour_tile_minutes: int = 60
    clock: Callable[[], float] = time.time

    def __post_init__(self) -> None:
        self.flights = SingleFlight()

    async def _provider_value(self, tenant: str, entity: str, provider: str, now: float) -> tuple[dict[str, Any] | None, str, float | None]:
        policy = self.policies[provider]
        key = cache_key(provider, entity, tenant)
        hit = self.cache.lookup(key, policy, now)
        if hit.entry is not None:
            return hit.entry.payload, hit.tier or "cache", now - hit.entry.fetched_at

        async def call() -> Entry:
            payload = await self.providers[provider].fetch(entity)
            return Entry(provider=provider, payload=payload, fetched_at=self.clock(), tenant=tenant)

        try:
            entry = await self.flights.do(key, call)
        except ProviderError:
            if hit.fallback is not None:
                return hit.fallback.payload, "stale_if_error", now - hit.fallback.fetched_at
            return None, "missing", None
        self.cache.store(key, entry, policy, self.clock())
        return entry.payload, "provider", 0.0

    async def get(self, tenant: str, entity: str, names: list[str]) -> dict[str, FeatureValue]:
        now = self.clock()
        unknown = set(names) - set(self.features.names())
        if unknown:
            raise KeyError(f"unknown features: {sorted(unknown)}")
        pk = partition_key(tenant, entity)
        end = tiles.minute_of(now)
        out: dict[str, FeatureValue] = {}
        for f in self.features.stream:
            if f.name in names:
                total = stream_value(self.store, pk, f.window_minutes, end, self.hour_tile_minutes)
                out[f.name] = FeatureValue(f.name, tiles.value(f, total), "stream", 0.0)
        wanted = [f for f in self.features.provider if f.name in names]
        results = await asyncio.gather(*(self._provider_value(tenant, entity, f.provider, now) for f in wanted))
        for pf, (payload, source, age) in zip(wanted, results, strict=True):
            out[pf.name] = FeatureValue(pf.name, payload, source, age)
        return out
