from __future__ import annotations

import copy
from typing import Any

import pytest

from dfp.config import load
from dfp.features.spec import FeatureSet, parse
from dfp.sim.world import World, simulate


def small_world_cfg() -> dict[str, Any]:
    cfg = copy.deepcopy(load("world"))
    cfg.update(days=4, tenants=3, customers_per_tenant=70)
    cfg["outages"] = [{"provider": "open_banking", "day": 2, "start_hour": 14, "hours": 2}]
    return cfg


@pytest.fixture(scope="session")
def world() -> World:
    return simulate(11, small_world_cfg())


@pytest.fixture(scope="session")
def features() -> FeatureSet:
    return parse(load("features"))
