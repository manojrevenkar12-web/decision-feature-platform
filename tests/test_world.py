import numpy as np

from dfp.sim.world import simulate
from tests.conftest import small_world_cfg


def test_same_seed_same_world() -> None:
    a, b = simulate(5, small_world_cfg()), simulate(5, small_world_cfg())
    assert np.array_equal(a.ev_time, b.ev_time) and np.array_equal(a.deliver_event, b.deliver_event)
    assert np.array_equal(a.provider_latency["bureau"], b.provider_latency["bureau"])


def test_the_stream_redelivers_and_delivers_late(world) -> None:
    assert len(world.deliver_time) > len(world.ev_time)
    assert np.all(np.diff(world.deliver_time) >= 0)
    assert ((world.ev_arrival - world.ev_time) > 3600).any()


def test_providers_answer_with_their_record_at_call_time(world) -> None:
    line = world.observed().providers
    person = next(p for p, ch in enumerate(world.changes["bureau"]) if len(ch) and world.start < ch[-1] < world.start + 3 * 86400)
    t = float(world.changes["bureau"][person][-1])
    found = []
    for attempt in range(2):
        for dec in range(len(world.dec_time)):
            lat, ok, before = line.call("bureau", person, dec, attempt, t - 1)
            if not ok:
                continue
            _, ok2, after = line.call("bureau", person, dec, attempt, t + 1)
            if ok2:
                found.append((before["v"], after["v"]))
                break
        if found:
            break
    assert found and found[0][1] == found[0][0] + 1


def test_some_people_are_customers_of_two_lenders(world) -> None:
    assert len(np.unique(world.cust_person)) < len(world.cust_person)
