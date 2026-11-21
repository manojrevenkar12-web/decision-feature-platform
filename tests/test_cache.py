import boto3
import fakeredis
import pytest
from moto import mock_aws

from dfp.cache.multilevel import MultiLevelCache, cache_key
from dfp.cache.policy import DAY, FreshnessPolicy, from_rules
from dfp.cache.tiers import DynamoTier, Entry, LruTier, RedisTier
from dfp.config import load

H = 3600.0


def entry(t: float, tenant: str = "t1") -> Entry:
    return Entry("bureau", {"score": 640}, fetched_at=t, tenant=tenant)


def test_max_age() -> None:
    p = FreshnessPolicy(max_age_s=7 * DAY)
    assert p.fresh(0, 7 * DAY)
    assert not p.fresh(0, 7 * DAY + 1)
    assert not p.fresh(10, 5)  # a response from the future is never served


def test_sanctions_result_must_follow_the_last_list_publication() -> None:
    p = FreshnessPolicy(max_age_s=DAY, not_before_daily_hour=6)
    day = 100 * DAY
    assert p.fresh(day + 5 * H, day + 5.5 * H)  # same window, before 06:00
    assert not p.fresh(day + 5 * H, day + 6.5 * H)  # the list was republished at 06:00
    assert p.fresh(day + 6.2 * H, day + 23 * H)


def test_stale_if_error_has_its_own_limit() -> None:
    p = FreshnessPolicy(max_age_s=7 * DAY, stale_if_error_s=DAY)
    assert not p.fresh(0, 7.5 * DAY) and p.usable_on_error(0, 7.5 * DAY)
    assert not p.usable_on_error(0, 8.1 * DAY)
    assert not FreshnessPolicy(max_age_s=H).usable_on_error(0, 1.5 * H)


def test_rules_from_config() -> None:
    rules = from_rules(load("compliance"))
    assert not rules["device_risk"].cacheable
    assert rules["sanctions"].not_before_daily_hour == 6


def test_keys_carry_the_tenant() -> None:
    assert cache_key("bureau", "p1", "t1") != cache_key("bureau", "p1", "t2")


def test_lru_evicts_and_expires() -> None:
    t = LruTier("l1", capacity=2)
    t.put("a", entry(0), 10, now=0)
    t.put("b", entry(0), 10, now=0)
    t.get("a", now=1)
    t.put("c", entry(0), 10, now=1)
    assert t.get("b", now=1) is None and t.get("a", now=1) is not None
    assert t.get("a", now=11) is None


def test_lookup_promotes_and_keeps_a_fallback() -> None:
    l1, l2 = LruTier("l1", 10), LruTier("redis", 10)
    cache = MultiLevelCache([l1, l2])
    pol = FreshnessPolicy(max_age_s=100, stale_if_error_s=50)
    cache.store("k", entry(0), pol, now=0)
    l1.clear()
    hit = cache.lookup("k", pol, now=20)
    assert hit.tier == "redis" and l1.get("k", now=20) is not None
    # past max age: no hit, but the entry may stand in when the provider fails
    stale = cache.lookup("k", pol, now=120)
    assert stale.entry is None and stale.fallback is not None


def test_uncacheable_providers_are_never_stored() -> None:
    l1 = LruTier("l1", 10)
    MultiLevelCache([l1]).store("k", entry(0), FreshnessPolicy(max_age_s=0), now=0)
    assert l1.get("k", now=0) is None


def test_redis_tier_roundtrip() -> None:
    r = RedisTier(fakeredis.FakeRedis())
    r.put("k", entry(5.0), 60, now=5.0)
    assert r.get("k", now=6.0) == entry(5.0)


@pytest.fixture
def ddb():
    with mock_aws():
        c = boto3.client("dynamodb", region_name="eu-central-1")
        c.create_table(
            TableName="cache",
            KeySchema=[{"AttributeName": "key", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "key", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield c


def test_dynamo_tier_ignores_items_ttl_has_not_deleted_yet(ddb) -> None:
    t = DynamoTier(ddb, "cache")
    t.put("k", entry(0), 60, now=0)
    assert t.get("k", now=30) == entry(0)
    assert t.get("k", now=61) is None
