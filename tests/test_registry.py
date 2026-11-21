import os

import pytest
from sqlalchemy import create_engine

from dfp.registry import db


def engines() -> list[str]:
    urls = ["sqlite://"]
    if os.environ.get("DFP_TEST_PG_URL"):
        urls.append(os.environ["DFP_TEST_PG_URL"])
    return urls


@pytest.fixture(params=engines())
def engine(request):
    e = create_engine(request.param)
    db.metadata.drop_all(e)
    db.migrate(e)
    yield e
    db.metadata.drop_all(e)


def test_tenant_comes_from_the_key(engine) -> None:
    db.add_tenant(engine, "t1", "Lender One", "key-one")
    assert db.tenant_for_key(engine, "key-one") == "t1"
    assert db.tenant_for_key(engine, "key-two") is None


def test_keys_are_stored_hashed(engine) -> None:
    db.add_tenant(engine, "t1", "Lender One", "key-one")
    with engine.connect() as c:
        stored = [r[0] for r in c.execute(db.api_keys.select())]
    assert "key-one" not in stored and db.hash_key("key-one") in stored


def test_definitions_are_versioned_and_immutable(engine) -> None:
    v1 = db.register(engine, "txn_sum_24h", "stream", {"agg": "sum", "window_minutes": 1440})
    assert db.register(engine, "txn_sum_24h", "stream", {"window_minutes": 1440, "agg": "sum"}) == v1
    v2 = db.register(engine, "txn_sum_24h", "stream", {"agg": "sum", "window_minutes": 720})
    assert (v1, v2) == (1, 2)
    assert db.active(engine)["txn_sum_24h"] == (2, "stream", {"agg": "sum", "window_minutes": 720})
