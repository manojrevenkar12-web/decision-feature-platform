"""Replays one `Observed` world through one design and records what each decision was served.

The design runs the production code paths: the stream `Consumer` into a bucket store, the tile plan
and `tiles.value` for reads, `MultiLevelCache` with `FreshnessPolicy`, and `Breaker`. What the
simulation adds is time: deliveries and decisions are merged in time order, provider calls take the
world's latency, cache writes land when a call completes, and the latency of every tier comes from
the world's draws for that decision, so every design pays the same luck.

Coalescing is modelled as the platform does it across Lambda containers: the first miss takes a
Redis lease, the others wait for the entry (`dfp.cache.lease`).
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from dfp.cache.multilevel import MultiLevelCache, cache_key
from dfp.cache.policy import FreshnessPolicy, from_rules, single_ttl
from dfp.cache.tiers import Entry, LruTier, Tier
from dfp.config import design as design_cfg
from dfp.config import load
from dfp.features import tiles
from dfp.features.spec import FeatureSet, StreamFeature
from dfp.providers.breaker import Breaker
from dfp.service.features import stream_value
from dfp.sim.world import PROVIDERS, Observed
from dfp.stream.consumer import Consumer, partition_key
from dfp.stream.events import TxnEvent
from dfp.stream.store import InMemoryBucketStore

SOURCES = ("missing", "provider", "l1", "redis", "dynamodb", "coalesced", "stale_if_error")
SRC = {s: i for i, s in enumerate(SOURCES)}
LEASE_POLL_MS = 12.5
OVERHEAD_MS = 2.0
TIER_FIXED_MS = {"l1": 0.02}


@dataclass
class Served:
    """What one design served, one row per decision."""

    design: str
    latency_ms: np.ndarray
    cost_eur: np.ndarray
    calls: np.ndarray
    failed: np.ndarray
    failed_missing: np.ndarray  # a required feature could not be served (the rest are over budget)
    cold: np.ndarray
    stream: dict[str, np.ndarray]
    version: dict[str, np.ndarray]  # report version served (-1 = not served / not needed)
    fetched_at: dict[str, np.ndarray]
    source: dict[str, np.ndarray]
    paid_by: dict[str, np.ndarray]  # tenant who bought the served report
    needed: dict[str, np.ndarray]
    consumer: dict[str, int] = field(default_factory=dict)
    evictions: int = 0


class _Aurora:
    """The status quo: every arrived event is a row (primary key on event id) and a decision runs one
    indexed range query over the widest window."""

    def __init__(self) -> None:
        self.rows: dict[int, list[tuple[float, int, bool, int]]] = {}
        self.seen: set[int] = set()

    def insert(self, eid: int, cust: int, t: float, amount: int, declined: bool, merchant: int) -> None:
        if eid in self.seen:
            return
        self.seen.add(eid)
        self.rows.setdefault(cust, []).append((t, amount, declined, merchant))

    def query(self, cust: int, features: tuple[StreamFeature, ...], now: float) -> tuple[dict[str, float], int]:
        rows = self.rows.get(cust, [])
        end = tiles.minute_of(now)
        widest = max(f.window_minutes for f in features)
        scanned = [r for r in rows if end - widest < tiles.minute_of(r[0]) <= end]
        out = {}
        for f in features:
            b = tiles.Bucket()
            for t, amount, declined, merchant in scanned:
                if end - f.window_minutes < tiles.minute_of(t):
                    b.add(amount, declined, merchant)
            out[f.name] = tiles.value(f, b)
        return out, len(scanned)


def _policies(spec: dict[str, Any]) -> dict[str, FreshnessPolicy]:
    if "single_ttl_hours" in spec:
        return single_ttl(list(PROVIDERS), float(spec["single_ttl_hours"]))
    return from_rules(load("compliance"))


def run(name: str, obs: Observed, features: FeatureSet, platform: dict[str, Any] | None = None) -> Served:
    platform = platform or load("platform")
    spec = design_cfg(name)
    policies = _policies(spec)
    n = len(obs.dec_time)
    budget = float(platform["latency_budget_ms"])
    timeout = float(platform["provider_timeout_ms"])
    tile = int(platform["tiles"]["hour_tile_minutes"])

    # stream side
    use_stream = spec["stream"] == "stream"
    store = InMemoryBucketStore(idempotency_ttl_s=platform["idempotency_ttl_hours"] * 3600)
    consumer = Consumer(
        store=store,
        retention_minutes=int(platform["tiles"]["retention_minutes"]),
        hour_tile_minutes=tile,
        time_basis=spec.get("time_basis", "event"),
        dedupe=bool(spec.get("dedupe", True)),
    )
    aurora = _Aurora()
    events = [
        TxnEvent(str(i), str(obs.cust_tenant[c]), str(c), float(t), int(a), int(m), bool(dl))
        for i, c, t, a, m, dl in zip(obs.ev_id, obs.ev_cust, obs.ev_time, obs.ev_amount, obs.ev_merchant, obs.ev_declined, strict=True)
    ]

    # cache side
    mode = spec.get("cache", "none")
    redis = LruTier("redis", int(platform["redis"]["capacity_keys"]))
    dynamo = LruTier("dynamodb", 10**9)
    n_ct = int(obs.infra["warm_containers"])
    l1 = [LruTier("l1", int(platform["l1"]["capacity"]), float(platform["l1"]["max_ttl_s"])) for _ in range(n_ct)]

    def tiers_for(c: int) -> list[Tier]:
        if mode == "tiered":
            return [l1[c], redis, dynamo]
        if mode == "l1_redis":
            return [l1[c], redis]
        if mode == "redis_only":
            return [redis]
        return []

    key_by_tenant = bool(spec.get("key_by_tenant", True))
    coalesce = bool(spec.get("coalesce", False))
    stale_ok = bool(spec.get("stale_if_error", False))
    breakers = {p: Breaker(**platform["breaker"]) for p in PROVIDERS} if spec.get("breaker") else {}
    inflight: dict[str, tuple[float, Entry | None]] = {}
    pending: list[tuple[float, int, str, Entry, int]] = []  # (completes_at, seq, key, entry, container)
    seq = 0

    next_recycle = [0] * n_ct
    cold_flag = [False] * n_ct

    out = Served(
        design=name,
        latency_ms=np.zeros(n),
        cost_eur=np.zeros(n),
        calls=np.zeros(n, dtype=np.int64),
        failed=np.zeros(n, dtype=bool),
        failed_missing=np.zeros(n, dtype=bool),
        cold=np.zeros(n, dtype=bool),
        stream={f.name: np.zeros(n) for f in features.stream},
        version={p: np.full(n, -1, dtype=np.int64) for p in PROVIDERS},
        fetched_at={p: np.full(n, np.nan) for p in PROVIDERS},
        source={p: np.zeros(n, dtype=np.int8) for p in PROVIDERS},
        paid_by={p: np.full(n, -1, dtype=np.int64) for p in PROVIDERS},
        needed={p: np.zeros(n, dtype=bool) for p in PROVIDERS},
    )
    di = 0
    n_deliv = len(obs.deliver_time)
    last_evict_day = -1

    for i in range(n):
        t = float(obs.dec_time[i])
        # 1. the stream catches up to t
        while di < n_deliv and obs.deliver_time[di] <= t:
            ev = events[int(obs.deliver_event[di])]
            now = float(obs.deliver_time[di])
            if use_stream:
                consumer.apply(ev, now)
            else:
                aurora.insert(int(ev.event_id), int(ev.entity), ev.event_time, ev.amount_cents, ev.declined, ev.merchant)
            di += 1
        day = int((t - obs.start) // 86400)
        if use_stream and day != last_evict_day:
            ret = tiles.minute_of(t) - int(platform["tiles"]["retention_minutes"]) - 60
            store.evict_before(ret, ret // tile)
            last_evict_day = day
        # 2. provider calls that completed by t land in the cache
        while pending and pending[0][0] <= t:
            done, _, key, landed, c = heapq.heappop(pending)
            MultiLevelCache(tiers_for(c)).store(key, landed, policies[landed.provider], done)
            if inflight.get(key, (0.0, None))[0] <= done:
                inflight.pop(key, None)
        # 3. which Lambda container serves this decision
        c = int(obs.container[i])
        while next_recycle[c] < len(obs.recycle[c]) and obs.recycle[c][next_recycle[c]] <= t:
            next_recycle[c] += 1
            l1[c].clear()
            cold_flag[c] = True
        cold = cold_flag[c]
        cold_flag[c] = False
        out.cold[i] = cold

        cust = int(obs.dec_cust[i])
        tenant = int(obs.cust_tenant[cust])
        person = int(obs.cust_person[cust])

        # 4. stream features
        if use_stream:
            pk = partition_key(str(tenant), str(cust))
            end = tiles.minute_of(t)
            before = store.items_read
            queries = 0
            for f in features.stream:
                total = stream_value(store, pk, f.window_minutes, end, tile)
                queries += tiles.plan(end, f.window_minutes, tile).queries
                out.stream[f.name][i] = tiles.value(f, total)
            items = store.items_read - before
            stream_ms = float(obs.dynamo_ms[i, 0]) * (1 + 0.15 * (queries - 1)) + items * obs.infra["dynamodb_per_item_ms"]
        else:
            vals, scanned = aurora.query(cust, features.stream, t)
            for k, v in vals.items():
                out.stream[k][i] = v
            stream_ms = float(obs.aurora_ms[i]) + scanned * obs.infra["aurora_per_row_ms"]

        # 5. provider features, in parallel
        slowest = 0.0
        failed = False
        for j, p in enumerate(PROVIDERS):
            if p == "kyb_registry" and not obs.cust_business[cust]:
                continue
            if p == "open_banking" and not obs.dec_open_banking[i]:
                continue
            out.needed[p][i] = True
            subject = person
            entity = f"d{i}" if p == "device_risk" else str(person)
            key = cache_key(p, entity, str(tenant) if key_by_tenant else None)
            pol = policies[p]
            lat = 0.0
            entry: Entry | None = None
            src = "missing"
            fallback: Entry | None = None
            tiers = tiers_for(c)
            if tiers and pol.cacheable:
                look = MultiLevelCache(tiers).lookup(key, pol, t)
                for depth, tn in enumerate(look.tiers_read):
                    draws = obs.redis_ms if tn == "redis" else obs.dynamo_ms
                    lat += TIER_FIXED_MS.get(tn) or float(draws[i, min(j + int(depth > 1), 5)])
                fallback = look.fallback
                if look.entry is not None:
                    entry, src = look.entry, str(look.tier)
            if entry is None and coalesce and key in inflight and inflight[key][0] > t:
                done, shared = inflight[key]
                lat += (done - t) * 1000 + LEASE_POLL_MS
                if shared is not None:
                    entry, src = shared, "coalesced"
            elif entry is None:
                # call the provider: one try, one retry if the budget allows
                elapsed = lat
                ok = False
                payload: dict[str, Any] = {}
                for attempt in range(2 if platform["retry_once"] else 1):
                    limit = timeout if attempt == 0 else budget - elapsed - 50
                    if attempt == 1 and limit < 150:
                        break
                    br = breakers.get(p)
                    if br is not None and not br.allow(t + elapsed / 1000):
                        elapsed += 0.5
                        break
                    call_ms, ok, payload = obs.providers.call(p, subject, i, attempt, t + elapsed / 1000)
                    out.calls[i] += 1
                    if call_ms > limit:
                        ok = False
                        elapsed += limit
                        out.cost_eur[i] += obs.provider_cost[p]  # the provider did the work
                    else:
                        elapsed += call_ms
                        if ok:
                            out.cost_eur[i] += obs.provider_cost[p]
                    if br is not None:
                        br.record(ok, t + elapsed / 1000)
                    if ok:
                        break
                lat = elapsed
                done = t + lat / 1000
                if ok:
                    entry = Entry(provider=p, payload=payload, fetched_at=done, tenant=str(tenant))
                    src = "provider"
                    if pol.cacheable and tiers:
                        seq += 1
                        heapq.heappush(pending, (done, seq, key, entry, c))
                if coalesce:
                    inflight[key] = (done, entry)
            if entry is None and stale_ok and fallback is not None:
                entry, src = fallback, "stale_if_error"
            if entry is None:
                failed = True
            else:
                out.version[p][i] = int(entry.payload["v"])
                out.fetched_at[p][i] = entry.fetched_at
                out.paid_by[p][i] = int(entry.tenant)
            out.source[p][i] = SRC[src]
            slowest = max(slowest, lat)

        out.latency_ms[i] = OVERHEAD_MS + max(stream_ms, slowest) + (float(obs.cold_ms[i]) if cold else 0.0)
        out.failed_missing[i] = failed
        out.failed[i] = failed or out.latency_ms[i] > budget

    st = consumer.stats
    out.consumer = {"applied": st.applied, "duplicates": st.duplicates, "too_late": st.too_late}
    out.evictions = redis.evictions
    return out
