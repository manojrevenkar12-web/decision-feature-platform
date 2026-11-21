import numpy as np
from pyiceberg.catalog.sql import SqlCatalog

from dfp.features.spec import StreamFeature
from dfp.offline import lake, pit


def test_as_of_counts_only_what_had_arrived() -> None:
    f = StreamFeature("c", "count", 60)
    et = np.array([1000.0, 1100.0, 1200.0])
    ar = np.array([1001.0, 1101.0, 9000.0])  # the third arrives two hours late
    z = np.zeros(3, dtype=np.int64)
    assert pit.as_of(f, 1300.0, et, ar, z, z.astype(bool), z) == 2
    assert pit.leaky(f, 1300.0, et, z, z.astype(bool), z) == 3


def test_iceberg_roundtrip_and_point_in_time_read(tmp_path) -> None:
    cat = SqlCatalog("local", uri=f"sqlite:///{tmp_path}/cat.db", warehouse=f"file://{tmp_path}")
    tbl = lake.table(cat)
    rows = [
        {
            "event_id": f"e{i}",
            "tenant": "t1",
            "entity": "c1",
            "event_time": 1000.0 + i,
            "arrival_time": 1000.0 + i * 100,
            "amount_cents": 100,
            "merchant": i,
            "declined": False,
        }
        for i in range(5)
    ] + [{"event_id": "x", "tenant": "t2", "entity": "c1", "event_time": 1000.0, "arrival_time": 1000.0, "amount_cents": 1, "merchant": 1, "declined": False}]
    lake.append(tbl, rows)
    got = lake.read_as_of(tbl, "t1", "c1", 1250.0)
    assert sorted(got.column("event_id").to_pylist()) == ["e0", "e1", "e2"]
