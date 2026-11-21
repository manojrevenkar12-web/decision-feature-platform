import asyncio

import fakeredis

from dfp.cache.lease import RedisLease
from dfp.cache.singleflight import SingleFlight
from dfp.cache.tiers import Entry
from dfp.providers.breaker import Breaker


def test_concurrent_misses_share_one_call() -> None:
    calls = 0

    async def fetch() -> int:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return 42

    async def main() -> list[int]:
        sf = SingleFlight()
        return await asyncio.gather(*(sf.do("k", fetch) for _ in range(5)))

    assert asyncio.run(main()) == [42] * 5 and calls == 1


def test_a_failed_call_fails_every_waiter_and_is_not_cached() -> None:
    async def boom() -> int:
        await asyncio.sleep(0.01)
        raise RuntimeError("provider down")

    async def main() -> list[object]:
        sf = SingleFlight()
        out = await asyncio.gather(*(sf.do("k", boom) for _ in range(3)), return_exceptions=True)
        assert "k" not in sf._inflight
        return out

    assert all(isinstance(x, RuntimeError) for x in asyncio.run(main()))


def test_redis_lease_coalesces_across_containers() -> None:
    r = fakeredis.FakeRedis()
    shared: dict[str, Entry] = {}
    calls = 0

    async def fetch() -> Entry:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        e = Entry("bureau", {"score": 1}, 0.0, "t1")
        shared["k"] = e
        return e

    async def main() -> list[Entry]:
        a, b = RedisLease(r, poll_ms=5), RedisLease(r, poll_ms=5)  # two containers
        return await asyncio.gather(a.do("k", lambda: shared.get("k"), fetch), b.do("k", lambda: shared.get("k"), fetch))

    out = asyncio.run(main())
    assert calls == 1 and out[0] == out[1]
    assert not r.exists("dfp:lease:k")


def test_breaker_opens_then_probes() -> None:
    b = Breaker(failures_to_open=3, cooldown_s=10)
    for t in range(3):
        b.record(False, t)
    assert b.open and not b.allow(5)
    assert b.allow(13)  # one probe after the cooldown
    assert not b.allow(13.5)
    b.record(True, 14)
    assert not b.open and b.allow(14)
