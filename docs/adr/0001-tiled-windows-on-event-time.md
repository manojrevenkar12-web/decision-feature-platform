# 1. Tiled windows on event time, read as of arrival

## Context
Decision flows read counts, sums, ratios and distinct counts over windows from 10 minutes to 7 days. Reading
10,080 minute buckets for a 7-day window is too slow. Pre-aggregating only hourly gives wrong answers at the
window edges. Kinesis delivers events late, sometimes hours late.

## Decision
- Windows are minute-aligned: a window of w minutes at decision time t covers event minutes (minute(t) − w, minute(t)].
- Each event updates one minute bucket and one hour tile, keyed by the minute it **happened** (event time).
- A read plans full hour tiles inside the window and minute buckets at its two ragged edges: at most three
  DynamoDB range queries per window, and an exact answer (`tests/test_tiles.py` checks it against brute force).
- The value served is what had **arrived** by t. The offline store records the arrival time, so a backfill reads
  `as_of` arrival and matches production.

## Consequences
- Minute buckets are kept for the longest window plus an hour (TTL), so storage grows with the longest window.
- An event that arrives after its window has passed is still counted for later windows, never for decisions already made.
- Counting by arrival time instead got 17% of decisions' stream features wrong in the lab.
