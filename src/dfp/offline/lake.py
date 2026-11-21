"""The offline store: transaction events as they arrived, in an Apache Iceberg table partitioned by
tenant and day. Locally the catalog is SQLite; on AWS it is Glue, and Athena reads the same table."""

from __future__ import annotations

from typing import Any

import pyarrow as pa
from pyiceberg.catalog import Catalog
from pyiceberg.expressions import And, EqualTo, LessThanOrEqual
from pyiceberg.partitioning import PartitionField, PartitionSpec
from pyiceberg.schema import Schema
from pyiceberg.transforms import DayTransform, IdentityTransform
from pyiceberg.types import BooleanType, DoubleType, LongType, NestedField, StringType, TimestamptzType

SCHEMA = Schema(
    NestedField(1, "event_id", StringType(), required=True),
    NestedField(2, "tenant", StringType(), required=True),
    NestedField(3, "entity", StringType(), required=True),
    NestedField(4, "event_time", DoubleType(), required=True),
    NestedField(5, "arrival_time", DoubleType(), required=True),
    NestedField(6, "arrival_ts", TimestamptzType(), required=True),
    NestedField(7, "amount_cents", LongType(), required=True),
    NestedField(8, "merchant", LongType(), required=True),
    NestedField(9, "declined", BooleanType(), required=True),
)
SPEC = PartitionSpec(
    PartitionField(source_id=2, field_id=1000, transform=IdentityTransform(), name="tenant"),
    PartitionField(source_id=6, field_id=1001, transform=DayTransform(), name="arrival_day"),
)
ARROW = pa.schema(
    [
        pa.field("event_id", pa.string(), nullable=False),
        pa.field("tenant", pa.string(), nullable=False),
        pa.field("entity", pa.string(), nullable=False),
        pa.field("event_time", pa.float64(), nullable=False),
        pa.field("arrival_time", pa.float64(), nullable=False),
        pa.field("arrival_ts", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("amount_cents", pa.int64(), nullable=False),
        pa.field("merchant", pa.int64(), nullable=False),
        pa.field("declined", pa.bool_(), nullable=False),
    ]
)


def table(catalog: Catalog, name: str = "features.txn_events") -> Any:
    ns = name.split(".")[0]
    if (ns,) not in catalog.list_namespaces():
        catalog.create_namespace(ns)
    if catalog.table_exists(name):
        return catalog.load_table(name)
    return catalog.create_table(name, schema=SCHEMA, partition_spec=SPEC)


def append(tbl: Any, rows: list[dict[str, Any]]) -> None:
    """Appends arrived events. Landing is keyed by event_id: callers pass each event once (the stream
    consumer's dedupe claim decides), so a redelivered batch never lands twice."""
    import datetime as dt

    for r in rows:
        r.setdefault("arrival_ts", dt.datetime.fromtimestamp(r["arrival_time"], tz=dt.UTC))
    tbl.append(pa.Table.from_pylist(rows, schema=ARROW))


def read_as_of(tbl: Any, tenant: str, entity: str, t: float) -> pa.Table:
    """Events of one entity that had arrived by t: the input to `pit.as_of`."""
    flt = And(And(EqualTo("tenant", tenant), EqualTo("entity", entity)), LessThanOrEqual("arrival_time", t))  # type: ignore[call-arg,arg-type]
    return tbl.scan(row_filter=flt).to_arrow()
