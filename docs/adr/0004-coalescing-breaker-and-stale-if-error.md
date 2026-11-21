# 4. Coalescing across containers, breaker, and stale-if-error

## Context
A double-submitted application runs the same flow twice within a second, usually on two Lambda containers. Both
miss the cache and both pay. During a provider outage, every call waits for the full timeout.

## Decision
- `SingleFlight` merges concurrent misses inside a container. `RedisLease` merges them across containers: the
  first miss takes `SET NX PX`, and the others poll the cache until the entry lands or the lease lapses.
- A circuit breaker per provider opens after five consecutive failures and probes after 30 seconds.
- When a provider fails, an older report is served only if its rule allows stale-if-error (bureau 24 h,
  registry 7 days). It is marked `stale_if_error` in the response. Sanctions, device and open banking have no grace.
- One retry, only if the remaining budget leaves at least 150 ms for it.

## Consequences
In the lab, coalescing saved about 3% of spend at a 15% double-submit rate. The breaker and stale-if-error mostly
shorten outage latency and keep a few hundred decisions automated. Open-banking outages still refer decisions to a
person, because no rule allows a stale balance.
