"""Loads the YAML files in config/. Each reader names the file it needs, so the boundary tests can
check that the world never reads the platform's settings."""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config"


@cache
def load(name: str) -> dict[str, Any]:
    with (CONFIG / f"{name}.yml").open() as f:
        data: dict[str, Any] = yaml.safe_load(f)
    return data


def design(name: str) -> dict[str, Any]:
    """A design's settings with its `base` resolved (ablations override the platform)."""
    designs = load("platform")["designs"]
    spec = dict(designs[name])
    if "base" in spec:
        base = design(spec.pop("base"))
        base.update(spec)
        return base
    return spec
