import numpy as np

from dfp.features import tiles
from dfp.features.spec import StreamFeature
from dfp.service.features import stream_value
from dfp.stream.store import InMemoryBucketStore


def covered(p: tiles.Plan, tile: int) -> list[int]:
    out = []
    for lo, hi in p.minute_ranges:
        out += list(range(lo, hi + 1))
    if p.hour_range:
        for h in range(p.hour_range[0], p.hour_range[1] + 1):
            out += list(range(h * tile, (h + 1) * tile))
    return sorted(out)


def test_plan_covers_each_minute_of_the_window_exactly_once() -> None:
    rng = np.random.default_rng(0)
    for _ in range(400):
        end = int(rng.integers(10_000, 10_000_000))
        w = int(rng.choice([1, 7, 10, 59, 60, 61, 119, 1440, 10080]))
        assert covered(tiles.plan(end, w), 60) == list(range(end - w + 1, end + 1))


def test_seven_day_window_reads_at_most_three_ranges() -> None:
    p = tiles.plan(29_000_017, 10080)
    assert p.queries <= 3
    assert p.hour_range is not None and p.hour_range[1] - p.hour_range[0] + 1 <= 168


def test_tiled_read_equals_brute_force() -> None:
    rng = np.random.default_rng(1)
    store = InMemoryBucketStore()
    times = np.sort(rng.uniform(0, 9 * 86400, size=3000))
    amounts = rng.integers(100, 10_000, size=3000)
    merchants = rng.integers(0, 50, size=3000)
    declined = rng.uniform(size=3000) < 0.1
    for i, t in enumerate(times):
        m = tiles.minute_of(t)
        store.apply(str(i), "a", m, m // 60, int(amounts[i]), bool(declined[i]), int(merchants[i]), now=t)
    for f in (StreamFeature("c", "count", 10), StreamFeature("s", "sum", 1440), StreamFeature("d", "distinct", 10080), StreamFeature("r", "declined_ratio", 60)):
        for now in rng.uniform(8 * 86400, 9 * 86400, size=30):
            end = tiles.minute_of(now)
            mask = ((times // 60) > end - f.window_minutes) & ((times // 60) <= end)
            got = tiles.value(f, stream_value(store, "a", f.window_minutes, end, 60))
            if f.agg == "count":
                want = float(mask.sum())
            elif f.agg == "sum":
                want = amounts[mask].sum() / 100
            elif f.agg == "distinct":
                want = float(len(set(merchants[mask])))
            else:
                want = declined[mask].sum() / mask.sum() if mask.sum() else 0.0
            assert np.isclose(got, want), (f, now)
