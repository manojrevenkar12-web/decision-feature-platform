"""Lambda entry points. Wiring reads environment variables set by infra/template.yaml."""

from __future__ import annotations

import os
import time
from functools import cache
from typing import Any

from dfp.cache.multilevel import MultiLevelCache
from dfp.cache.policy import from_rules
from dfp.cache.tiers import DynamoTier, LruTier, RedisTier
from dfp.config import load
from dfp.features.spec import parse
from dfp.providers.breaker import Breaker
from dfp.providers.client import HttpProvider, Resilient
from dfp.service.features import FeatureService
from dfp.stream.consumer import Consumer
from dfp.stream.store import DynamoBucketStore


@cache
def _clients() -> tuple[Any, Any]:
    import boto3
    import redis

    return boto3.client("dynamodb"), redis.Redis.from_url(os.environ["REDIS_URL"], socket_timeout=0.05)


@cache
def _store() -> DynamoBucketStore:
    ddb, _ = _clients()
    cfg = load("platform")
    return DynamoBucketStore(ddb, os.environ["BUCKETS_TABLE"], os.environ["IDEMPOTENCY_TABLE"], idempotency_ttl_s=cfg["idempotency_ttl_hours"] * 3600)


def stream_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    cfg = load("platform")
    consumer = Consumer(store=_store(), retention_minutes=cfg["tiles"]["retention_minutes"], hour_tile_minutes=cfg["tiles"]["hour_tile_minutes"])
    return consumer.handle_batch(event["Records"], now=time.time())


@cache
def _app() -> Any:
    from mangum import Mangum
    from sqlalchemy import create_engine

    from dfp.api.app import create_app
    from dfp.registry.db import tenant_for_key

    ddb, rds = _clients()
    cfg = load("platform")
    providers = {
        p: Resilient(HttpProvider(p, os.environ["PROVIDER_GATEWAY_URL"], os.environ["PROVIDER_API_KEY"], cfg["provider_timeout_ms"] / 1000), Breaker(**cfg["breaker"]))
        for p in load("compliance")["providers"]
    }
    service = FeatureService(
        features=parse(load("features")),
        store=_store(),
        cache=MultiLevelCache([LruTier("l1", cfg["l1"]["capacity"], cfg["l1"]["max_ttl_s"]), RedisTier(rds), DynamoTier(ddb, os.environ["CACHE_TABLE"])]),
        policies=from_rules(load("compliance")),
        providers=dict(providers),
        hour_tile_minutes=cfg["tiles"]["hour_tile_minutes"],
    )
    engine = create_engine(os.environ["REGISTRY_URL"], pool_pre_ping=True)
    return Mangum(create_app(service, lambda key: tenant_for_key(engine, key)))


def api_handler(event: dict[str, Any], context: Any) -> Any:
    return _app()(event, context)
