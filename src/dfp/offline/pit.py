"""Point-in-time features for the offline store: what a backfill or a backtest should see.

The online value at decision time t counted only events that had arrived by t. A backfill that
filters on event time alone also counts late events that arrived after t, so the model trains on
values production never served. `as_of` uses arrival time and matches production; `leaky` is the
naive backfill, kept so the report can show the skew.
"""

from __future__ import annotations

import numpy as np

from dfp.features.spec import StreamFeature


def _window(event_minute: np.ndarray, t: float, w: int) -> np.ndarray:
    end = int(t // 60)
    return (event_minute > end - w) & (event_minute <= end)


def _agg(f: StreamFeature, mask: np.ndarray, amount: np.ndarray, declined: np.ndarray, merchant: np.ndarray) -> float:
    n = int(mask.sum())
    if f.agg == "count":
        return float(n)
    if f.agg == "sum":
        return float(amount[mask].sum()) / 100.0
    if f.agg == "distinct":
        return float(len(np.unique(merchant[mask])))
    return float(declined[mask].sum()) / n if n else 0.0


def as_of(f: StreamFeature, t: float, event_time: np.ndarray, arrival: np.ndarray, amount: np.ndarray, declined: np.ndarray, merchant: np.ndarray) -> float:
    mask = _window((event_time // 60).astype(np.int64), t, f.window_minutes) & (arrival <= t)
    return _agg(f, mask, amount, declined, merchant)


def leaky(f: StreamFeature, t: float, event_time: np.ndarray, amount: np.ndarray, declined: np.ndarray, merchant: np.ndarray) -> float:
    mask = _window((event_time // 60).astype(np.int64), t, f.window_minutes)
    return _agg(f, mask, amount, declined, merchant)
