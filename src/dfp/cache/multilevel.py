"""Read-through over the tiers, fastest first. A fresh hit is promoted to the faster tiers; an entry
that is too old to serve but allowed when the provider fails is kept aside as the fallback."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from dfp.cache.policy import FreshnessPolicy
from dfp.cache.tiers import Entry, Tier


def cache_key(provider: str, entity: str, tenant: str | None) -> str:
    """Keyed by tenant unless a design opts out: one lender's paid report is never another's."""
    return f"{provider}:{tenant}:{entity}" if tenant is not None else f"{provider}:*:{entity}"


@dataclass
class Lookup:
    entry: Entry | None
    tier: str | None
    fallback: Entry | None
    tiers_read: list[str] = field(default_factory=list)


@dataclass
class MultiLevelCache:
    tiers: Sequence[Tier]

    def lookup(self, key: str, policy: FreshnessPolicy, now: float) -> Lookup:
        read: list[str] = []
        fallback: Entry | None = None
        if not policy.cacheable:
            return Lookup(None, None, None, read)
        for i, tier in enumerate(self.tiers):
            read.append(tier.name)
            entry = tier.get(key, now)
            if entry is None:
                continue
            if policy.fresh(entry.fetched_at, now):
                for upper in self.tiers[:i]:
                    upper.put(key, entry, policy.max_age_s - (now - entry.fetched_at), now)
                return Lookup(entry, tier.name, fallback, read)
            if fallback is None and policy.usable_on_error(entry.fetched_at, now):
                fallback = entry
        return Lookup(None, None, fallback, read)

    def store(self, key: str, entry: Entry, policy: FreshnessPolicy, now: float) -> None:
        if not policy.cacheable:
            return
        age = now - entry.fetched_at
        last = len(self.tiers) - 1
        for i, tier in enumerate(self.tiers):
            ttl = (policy.store_ttl_s() if i == last else policy.max_age_s) - age
            tier.put(key, entry, ttl, now)
