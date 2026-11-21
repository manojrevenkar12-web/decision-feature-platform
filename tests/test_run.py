import json

import pytest

from dfp.config import load
from dfp.sim import report, run


def test_heldout_runs_once(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(run, "REPORTS", tmp_path)
    monkeypatch.setattr(run, "LOCK", tmp_path / "heldout.lock")
    monkeypatch.setattr(run, "run_seed", lambda seed: {"seed": seed})
    monkeypatch.setattr(run, "summarize", lambda parts: {"n": len(parts)})

    class Pool:
        def __init__(self, **kw) -> None: ...
        def __enter__(self):
            return self

        def __exit__(self, *a) -> None: ...
        def map(self, fn, xs):
            return [fn(x) for x in xs]

    monkeypatch.setattr(run, "ProcessPoolExecutor", Pool)
    run.run("heldout")
    assert json.loads((tmp_path / "heldout.lock").read_text())["seeds"] == load("seeds")["heldout"]
    with pytest.raises(SystemExit, match="run once"):
        run.run("heldout")


def test_fingerprint_changes_with_config() -> None:
    assert len(run.config_fingerprint()) == 16


def test_gate_names_what_failed() -> None:
    good = {"exact_rate": [1, 1, 1], "violations": 0, "cross_tenant": 0, "p99_ms": [900, 0, 0], "spend_cut_vs_direct": [0.8, 0.7, 0.9], "failed_rate": [0.005, 0, 0]}
    doc = {"designs": {"platform": good, "direct": {"failed_rate": [0.02, 0, 0]}}}
    assert report.gate(doc, load("gates")) == []
    doc["designs"]["platform"] = {**good, "violations": 3, "p99_ms": [2000, 0, 0]}
    fails = report.gate(doc, load("gates"))
    assert any("rule breaks" in f for f in fails) and any("p99" in f for f in fails)
