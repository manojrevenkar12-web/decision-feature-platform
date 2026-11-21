from typing import Any

import pytest
from fastapi.testclient import TestClient

from dfp.api.app import create_app
from dfp.cache.multilevel import MultiLevelCache
from dfp.cache.policy import from_rules
from dfp.cache.tiers import LruTier
from dfp.config import load
from dfp.features import tiles
from dfp.features.spec import parse
from dfp.providers.client import ProviderError
from dfp.service.features import FeatureService
from dfp.stream.consumer import Consumer
from dfp.stream.events import TxnEvent
from dfp.stream.store import InMemoryBucketStore

NOW = 1_780_000_000.0


class FakeProvider:
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls = 0
        self.down = False

    async def fetch(self, entity: str) -> dict[str, Any]:
        self.calls += 1
        if self.down:
            raise ProviderError("down")
        return {"entity": entity, "score": 600 + self.calls}


@pytest.fixture
def setup():
    clock = {"t": NOW}
    store = InMemoryBucketStore()
    consumer = Consumer(store, retention_minutes=10_140)
    for i in range(5):
        consumer.apply(TxnEvent(f"e{i}", "t1", "c1", NOW - 120 - i * 60, 1000, i, i == 0), now=NOW - 100)
    providers = {p: FakeProvider(p) for p in load("compliance")["providers"]}
    service = FeatureService(
        features=parse(load("features")),
        store=store,
        cache=MultiLevelCache([LruTier("l1", 100), LruTier("redis", 1000)]),
        policies=from_rules(load("compliance")),
        providers=providers,  # type: ignore[arg-type]
        clock=lambda: clock["t"],
    )
    keys = {"key-1": "t1", "key-2": "t2"}
    client = TestClient(create_app(service, keys.get))
    return client, providers, clock


def post(client, key: str, features: list[str], entity: str = "c1"):
    return client.post("/v1/features", headers={"X-Api-Key": key}, json={"entity_id": entity, "features": features})


def test_unknown_key_is_rejected(setup) -> None:
    client, _, _ = setup
    assert post(client, "nope", ["txn_count_1h"]).status_code == 401
    assert client.get("/healthz").json() == {"status": "ok"}


def test_stream_features_are_scoped_to_the_keys_tenant(setup) -> None:
    client, _, _ = setup
    body = post(client, "key-1", ["txn_count_10m", "declined_ratio_1h"]).json()["features"]
    assert body["txn_count_10m"]["value"] == 5 and body["declined_ratio_1h"]["value"] == pytest.approx(0.2)
    other = post(client, "key-2", ["txn_count_10m"]).json()["features"]
    assert other["txn_count_10m"]["value"] == 0


def test_second_request_hits_the_cache_and_device_risk_never_does(setup) -> None:
    client, providers, clock = setup
    post(client, "key-1", ["bureau_score", "device_risk_score"])
    clock["t"] += 30
    body = post(client, "key-1", ["bureau_score", "device_risk_score"]).json()["features"]
    assert body["bureau_score"]["source"] == "l1" and body["bureau_score"]["age_s"] == pytest.approx(30)
    assert body["device_risk_score"]["source"] == "provider"
    assert providers["bureau"].calls == 1 and providers["device_risk"].calls == 2


def test_another_lender_pays_for_its_own_report(setup) -> None:
    client, providers, _ = setup
    post(client, "key-1", ["bureau_score"])
    assert post(client, "key-2", ["bureau_score"]).json()["features"]["bureau_score"]["source"] == "provider"
    assert providers["bureau"].calls == 2


def test_stale_if_error_only_where_the_rule_allows(setup) -> None:
    client, providers, clock = setup
    post(client, "key-1", ["bureau_score", "ob_cashflow_30d"])
    clock["t"] += 7 * 86400 + 3600  # past the bureau's 7 days, inside its 24 h grace
    providers["bureau"].down = providers["open_banking"].down = True
    body = post(client, "key-1", ["bureau_score", "ob_cashflow_30d"]).json()["features"]
    assert body["bureau_score"]["source"] == "stale_if_error"
    assert body["ob_cashflow_30d"]["source"] == "missing" and body["ob_cashflow_30d"]["value"] is None


def test_unknown_feature_is_a_422(setup) -> None:
    client, _, _ = setup
    assert post(client, "key-1", ["nope"]).status_code == 422
    assert post(client, "key-1", ["txn_count_1h"], entity="bad entity!").status_code == 422


def test_minute_alignment_matches_the_spec() -> None:
    assert tiles.minute_of(NOW) == int(NOW // 60)
