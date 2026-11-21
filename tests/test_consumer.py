import base64

import boto3
import pytest
from moto import mock_aws

from dfp.features import tiles
from dfp.stream.consumer import Consumer
from dfp.stream.events import TxnEvent
from dfp.stream.store import HOUR, MINUTE, DynamoBucketStore, InMemoryBucketStore


def ev(i: str, t: float, amount: int = 1000, merchant: int = 7, declined: bool = False) -> TxnEvent:
    return TxnEvent(i, "t1", "c1", t, amount, merchant, declined)


def record(e: TxnEvent, seq: str) -> dict:
    return {"kinesis": {"data": base64.b64encode(e.to_json().encode()).decode(), "sequenceNumber": seq}}


def total(store, lo: int, hi: int) -> tiles.Bucket:
    b = tiles.Bucket()
    for x in store.read("t1#c1", MINUTE, lo, hi):
        b.merge(x)
    return b


def test_a_redelivered_event_counts_once() -> None:
    c = Consumer(InMemoryBucketStore(), retention_minutes=10_140)
    assert c.apply(ev("e1", 6000.0), now=6001.0) == "applied"
    assert c.apply(ev("e1", 6000.0), now=6050.0) == "duplicate"
    assert total(c.store, 0, 10**6).count == 1


def test_a_late_event_lands_in_the_minute_it_happened() -> None:
    c = Consumer(InMemoryBucketStore(), retention_minutes=10_140)
    c.apply(ev("e1", 6000.0), now=6000.0 + 3 * 3600)
    assert total(c.store, 100, 100).count == 1  # minute 100 = 6000 s
    assert total(c.store, 101, 10**6).count == 0


def test_arrival_time_basis_files_it_under_arrival() -> None:
    c = Consumer(InMemoryBucketStore(), retention_minutes=10_140, time_basis="arrival", dedupe=False)
    c.apply(ev("e1", 6000.0), now=6000.0 + 3 * 3600)
    c.apply(ev("e1", 6000.0), now=6000.0 + 3 * 3600 + 5)
    assert total(c.store, 100, 100).count == 0
    assert total(c.store, 0, 10**6).count == 2


def test_events_older_than_retention_are_dropped() -> None:
    c = Consumer(InMemoryBucketStore(), retention_minutes=60)
    assert c.apply(ev("e1", 0.0), now=2 * 3600) == "too_late"
    assert c.stats.too_late == 1


def test_batch_reports_the_first_failure_so_lambda_retries_from_there() -> None:
    c = Consumer(InMemoryBucketStore(), retention_minutes=10_140)
    good, bad = record(ev("e1", 6000.0), "1"), {"kinesis": {"data": "not-base64-json", "sequenceNumber": "2"}}
    later = record(ev("e3", 6010.0), "3")
    assert c.handle_batch([good, bad, later], now=6100.0) == {"batchItemFailures": [{"itemIdentifier": "2"}]}
    # Lambda redelivers from sequence 2; the good record before it is not counted again
    c.handle_batch([good, later], now=6200.0)
    assert total(c.store, 0, 10**6).count == 2


@pytest.fixture
def dynamo():
    with mock_aws():
        client = boto3.client("dynamodb", region_name="eu-central-1")
        client.create_table(
            TableName="buckets",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}, {"AttributeName": "sk", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        client.create_table(
            TableName="idem",
            KeySchema=[{"AttributeName": "event_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "event_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield client


def test_dynamo_store_matches_in_memory(dynamo) -> None:
    mem = Consumer(InMemoryBucketStore(), retention_minutes=10_140)
    ddb = Consumer(DynamoBucketStore(dynamo, "buckets", "idem"), retention_minutes=10_140)
    events = [ev(f"e{i}", 6000.0 + i * 37, amount=100 + i, merchant=i % 4, declined=i % 5 == 0) for i in range(40)]
    for c in (mem, ddb):
        for e in events + events[:10]:  # ten redeliveries
            c.apply(e, now=e.event_time + 2)
    for kind, lo, hi in ((MINUTE, 0, 10**6), (HOUR, 0, 10**4)):
        a, b = tiles.Bucket(), tiles.Bucket()
        for x in mem.store.read("t1#c1", kind, lo, hi):
            a.merge(x)
        for x in ddb.store.read("t1#c1", kind, lo, hi):
            b.merge(x)
        assert (a.count, a.amount_cents, a.declined, a.merchants) == (b.count, b.amount_cents, b.declined, b.merchants)
    assert ddb.stats.duplicates == 10 and b.count == 40


def test_dynamo_claim_expires_after_its_ttl(dynamo) -> None:
    store = DynamoBucketStore(dynamo, "buckets", "idem", idempotency_ttl_s=60)
    assert store.apply("e1", "t1#c1", 100, 1, 500, False, 3, now=6000.0)
    assert not store.apply("e1", "t1#c1", 100, 1, 500, False, 3, now=6030.0)
    assert store.apply("e1", "t1#c1", 100, 1, 500, False, 3, now=6100.0)
