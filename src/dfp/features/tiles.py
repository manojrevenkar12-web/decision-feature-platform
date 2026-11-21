"""Tiled windows over minute buckets.

Each transaction updates one minute bucket and one hour tile. A window of w minutes ending at minute m
covers minutes (m - w, m]. It is read as the full hour tiles inside it plus the minute buckets at its
two ragged edges, so a 7-day window reads at most 167 hour tiles and 118 minute buckets instead of
10,080 minutes, and the answer is exact (`tests/test_tiles.py`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from dfp.features.spec import StreamFeature


def minute_of(ts: float) -> int:
    """Minute index since the epoch for a timestamp in seconds."""
    return int(ts // 60)


@dataclass
class Bucket:
    count: int = 0
    amount_cents: int = 0
    declined: int = 0
    merchants: set[int] = field(default_factory=set)

    def add(self, amount_cents: int, declined: bool, merchant: int) -> None:
        self.count += 1
        self.amount_cents += amount_cents
        self.declined += int(declined)
        self.merchants.add(merchant)

    def merge(self, other: Bucket) -> None:
        self.count += other.count
        self.amount_cents += other.amount_cents
        self.declined += other.declined
        self.merchants |= other.merchants


@dataclass(frozen=True)
class Plan:
    """Contiguous ranges to read: minute ranges at the edges, one range of hour tiles inside."""

    minute_ranges: tuple[tuple[int, int], ...]
    hour_range: tuple[int, int] | None

    @property
    def queries(self) -> int:
        return len(self.minute_ranges) + (1 if self.hour_range else 0)


def plan(end_minute: int, window_minutes: int, tile: int = 60) -> Plan:
    start = end_minute - window_minutes + 1
    first_hour = -(-start // tile)  # first tile that starts at or after `start`
    last_hour = (end_minute + 1) // tile - 1  # last tile that ends at or before `end_minute`
    if last_hour < first_hour:
        return Plan(minute_ranges=((start, end_minute),), hour_range=None)
    ranges = []
    if start <= first_hour * tile - 1:
        ranges.append((start, first_hour * tile - 1))
    if (last_hour + 1) * tile <= end_minute:
        ranges.append(((last_hour + 1) * tile, end_minute))
    return Plan(minute_ranges=tuple(ranges), hour_range=(first_hour, last_hour))


def value(feature: StreamFeature, total: Bucket) -> float:
    if feature.agg == "count":
        return float(total.count)
    if feature.agg == "sum":
        return total.amount_cents / 100.0
    if feature.agg == "distinct":
        return float(len(total.merchants))
    return total.declined / total.count if total.count else 0.0
