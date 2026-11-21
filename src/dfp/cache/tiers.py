"""Cache tiers: in-process LRU (per Lambda container), Redis, DynamoDB. Each stores an `Entry`
under a key with a TTL; the multi-level cache decides what to read and what to serve."""

from __future__ import annotations

import json
from collections import OrderedDict
from dataclasses import asdict, dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class Entry:
    provider: str
    payload: dict[str, Any]
    fetched_at: float
    tenant: str  # who paid for it

    def dumps(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))

    @classmethod
    def loads(cls, s: str | bytes) -> Entry:
        return cls(**json.loads(s))


class Tier(Protocol):
    name: str

    def get(self, key: str, now: float) -> Entry | None: ...

    def put(self, key: str, entry: Entry, ttl_s: float, now: float) -> None: ...


class LruTier:
    """Bounded LRU with per-key expiry. In production this is the L1 inside a Lambda container;
    the simulation also uses it to stand in for Redis under `maxmemory-policy allkeys-lru`."""

    def __init__(self, name: str, capacity: int, max_ttl_s: float | None = None) -> None:
        self.name = name
        self.capacity = capacity
        self.max_ttl_s = max_ttl_s
        self.data: OrderedDict[str, tuple[float, Entry]] = OrderedDict()
        self.evictions = 0

    def get(self, key: str, now: float) -> Entry | None:
        hit = self.data.get(key)
        if hit is None:
            return None
        expires, entry = hit
        if expires <= now:
            del self.data[key]
            return None
        self.data.move_to_end(key)
        return entry

    def put(self, key: str, entry: Entry, ttl_s: float, now: float) -> None:
        if self.max_ttl_s is not None:
            ttl_s = min(ttl_s, self.max_ttl_s)
        if ttl_s <= 0:
            return
        self.data[key] = (now + ttl_s, entry)
        self.data.move_to_end(key)
        while len(self.data) > self.capacity:
            self.data.popitem(last=False)
            self.evictions += 1

    def clear(self) -> None:
        self.data.clear()


class RedisTier:
    name = "redis"

    def __init__(self, client: Any, prefix: str = "dfp:") -> None:
        self.client = client
        self.prefix = prefix

    def get(self, key: str, now: float) -> Entry | None:
        raw = self.client.get(self.prefix + key)
        return None if raw is None else Entry.loads(raw)

    def put(self, key: str, entry: Entry, ttl_s: float, now: float) -> None:
        if ttl_s >= 1:
            self.client.set(self.prefix + key, entry.dumps(), ex=int(ttl_s))


class DynamoTier:
    """DynamoDB deletes expired items lazily (up to days later), so reads check `expires_at`."""

    name = "dynamodb"

    def __init__(self, client: Any, table: str) -> None:
        self.client = client
        self.table = table

    def get(self, key: str, now: float) -> Entry | None:
        item = self.client.get_item(TableName=self.table, Key={"key": {"S": key}}).get("Item")
        if item is None or float(item["expires_at"]["N"]) <= now:
            return None
        return Entry.loads(item["entry"]["S"])

    def put(self, key: str, entry: Entry, ttl_s: float, now: float) -> None:
        if ttl_s <= 0:
            return
        self.client.put_item(
            TableName=self.table,
            Item={"key": {"S": key}, "entry": {"S": entry.dumps()}, "expires_at": {"N": str(int(now + ttl_s))}},
        )
