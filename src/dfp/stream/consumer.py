"""The Kinesis consumer: one Lambda invocation per batch of transaction events.

Events land in the bucket of the minute they happened (event time), not the minute they arrived, and
each event id is applied once. On a failure the handler reports the first failed record, so Lambda
retries from there (`ReportBatchItemFailures`); everything after it is redelivered and the dedupe
claim keeps those from counting twice.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Literal

from dfp.features.tiles import minute_of
from dfp.stream.events import TxnEvent
from dfp.stream.store import BucketStore


def partition_key(tenant: str, entity: str) -> str:
    return f"{tenant}#{entity}"


@dataclass
class ConsumerStats:
    applied: int = 0
    duplicates: int = 0
    too_late: int = 0
    failed: int = 0
    by_reason: dict[str, int] = field(default_factory=dict)


@dataclass
class Consumer:
    store: BucketStore
    retention_minutes: int
    hour_tile_minutes: int = 60
    time_basis: Literal["event", "arrival"] = "event"
    dedupe: bool = True
    stats: ConsumerStats = field(default_factory=ConsumerStats)

    def apply(self, ev: TxnEvent, now: float) -> str:
        """Applies one event that arrived at `now`. Returns applied, duplicate or too_late."""
        ts = ev.event_time if self.time_basis == "event" else now
        minute = minute_of(ts)
        if minute < minute_of(now) - self.retention_minutes:
            self.stats.too_late += 1
            return "too_late"
        hour = minute // self.hour_tile_minutes
        pk = partition_key(ev.tenant, ev.entity)
        if self.dedupe:
            if not self.store.apply(ev.event_id, pk, minute, hour, ev.amount_cents, ev.declined, ev.merchant, now):
                self.stats.duplicates += 1
                return "duplicate"
        else:
            self.store.apply_unchecked(pk, minute, hour, ev.amount_cents, ev.declined, ev.merchant)
        self.stats.applied += 1
        return "applied"

    def handle_batch(self, records: Iterable[dict[str, Any]], now: float) -> dict[str, list[dict[str, str]]]:
        for rec in records:
            try:
                self.apply(TxnEvent.from_kinesis(rec), now)
            except Exception:  # noqa: BLE001 - any failure: report it and let Lambda retry from here
                self.stats.failed += 1
                return {"batchItemFailures": [{"itemIdentifier": rec["kinesis"]["sequenceNumber"]}]}
        return {"batchItemFailures": []}
