import numpy as np
import pytest

from dfp.sim import designs, evaluate


@pytest.fixture(scope="module")
def graded(world, features):
    obs = world.observed()
    known, _ = evaluate.truth_stream(world, features)
    versions = evaluate.truth_versions(world)
    out = {}
    for name in ("direct", "ttl_cache", "streaming_naive", "platform", "no_dedupe"):
        out[name] = evaluate.grade(world, designs.run(name, obs, features), known, versions)
    return out


def test_platform_serves_exact_stream_features_and_keeps_every_rule(graded) -> None:
    p = graded["platform"]
    assert p["exact"].all()
    assert p["violations"].sum() == 0 and p["cross_tenant"].sum() == 0


def test_platform_spends_less_than_querying_every_time(graded) -> None:
    assert graded["platform"]["cost_eur"].sum() < 0.5 * graded["direct"]["cost_eur"].sum()


def test_generic_cache_breaks_rules_and_naive_stream_miscounts(graded) -> None:
    assert graded["ttl_cache"]["violations"].sum() > 0
    assert graded["ttl_cache"]["cross_tenant"].sum() > 0
    assert graded["streaming_naive"]["exact"].mean() < 0.99
    assert graded["no_dedupe"]["exact"].mean() < 0.99


def test_every_design_is_graded_on_the_same_decisions(graded) -> None:
    sizes = {len(g["latency_ms"]) for g in graded.values()}
    assert len(sizes) == 1
    # direct and the generic cache call the provider on the same decisions with the same luck:
    # where both called on a decision's first try, they paid the same
    a, b = graded["direct"], graded["ttl_cache"]
    both = (a["calls"] > 0) & (b["calls"] == a["calls"])
    assert np.allclose(a["cost_eur"][both], b["cost_eur"][both])
