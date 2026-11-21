"""The truth stays in the world; the world does not read the platform's settings."""

import ast
import dataclasses
from pathlib import Path

from dfp.sim.world import Observed

SRC = Path(__file__).resolve().parents[1] / "src" / "dfp"
HIDDEN = {"ev_arrival", "changes", "version", "provider_latency", "provider_error", "device_score"}


def names_used(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    return {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}


def test_observed_carries_nothing_hidden() -> None:
    fields = {f.name for f in dataclasses.fields(Observed)}
    assert not fields & HIDDEN


def test_designs_and_the_platform_never_touch_the_world() -> None:
    for path in [SRC / "sim" / "designs.py", *SRC.glob("[!s]*/*.py"), *(SRC / "service").glob("*.py"), *(SRC / "stream").glob("*.py")]:
        used = names_used(path)
        assert "World" not in used and "simulate" not in used, path
        assert not used & {"ev_arrival", "changes", "provider_latency", "provider_error"}, path


def test_the_world_reads_only_its_own_config() -> None:
    text = (SRC / "sim" / "world.py").read_text()
    assert 'load("world")' in text
    for other in ("platform", "compliance", "features", "gates"):
        assert f'load("{other}")' not in text
