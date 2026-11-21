"""Runs every design on a seed set and writes reports/<set>.json.

Development seeds run as often as needed. Held-out seeds run once: the first run writes
reports/heldout.lock with the config fingerprint, and a second run refuses (AGENTS.md).
"""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from typing import Any

import numpy as np

from dfp.config import CONFIG, ROOT, design, load
from dfp.features.spec import parse
from dfp.sim import designs, evaluate
from dfp.sim.world import simulate

REPORTS = ROOT / "reports"
LOCK = REPORTS / "heldout.lock"
CONFIG_FILES = ("world.yml", "compliance.yml", "features.yml", "platform.yml", "gates.yml", "seeds.yml")


def config_fingerprint() -> str:
    h = hashlib.sha256()
    for name in CONFIG_FILES:
        h.update((CONFIG / name).read_bytes())
    return h.hexdigest()[:16]


def run_seed(seed: int) -> dict[str, Any]:
    world = simulate(seed)
    obs = world.observed()
    features = parse(load("features"))
    known, leak = evaluate.truth_stream(world, features)
    versions = evaluate.truth_versions(world)
    graded, extras = {}, {}
    for name in load("platform")["designs"]:
        served = designs.run(name, obs, features)
        graded[name] = evaluate.grade(world, served, known, versions)
        extras[name] = {**served.consumer, "redis_evictions": served.evictions}
    skew = {f: float(np.mean(~np.isclose(known[f], leak[f], rtol=0, atol=1e-9))) for f in known}
    late = world.ev_arrival - world.ev_time
    facts = {
        "events": int(len(world.ev_time)),
        "deliveries": int(len(world.deliver_time)),
        "redelivered": int(len(world.deliver_time) - len(world.ev_time)),
        "late_over_1m": int((late > 60).sum()),
        "decisions": int(len(world.dec_time)),
        "customers": int(len(world.cust_tenant)),
        "people_at_two_lenders": int(len(world.cust_person) - len(np.unique(world.cust_person))),
    }
    return {"seed": seed, "graded": graded, "days": evaluate.blocks(world), "extras": extras, "skew": skew, "facts": facts}


def summarize(parts: list[dict[str, Any]]) -> dict[str, Any]:
    names = list(parts[0]["graded"])
    labels = {n: design(n)["label"] for n in names}
    graded = {n: [p["graded"][n] for p in parts] for n in names}
    designs_out = evaluate.summarize(graded, [p["days"] for p in parts], labels)
    for n in names:
        designs_out[n]["stream_consumer"] = {k: int(sum(p["extras"][n][k] for p in parts)) for k in parts[0]["extras"][n]}
    lat_hist = {}
    edges = np.concatenate([np.arange(0, 1500, 25), [1500, 1e9]])
    for n in ("direct", "ttl_cache", "platform"):
        lat = np.concatenate([g["latency_ms"] for g in graded[n]])
        counts, _ = np.histogram(lat, bins=edges)
        lat_hist[n] = [int(c) for c in counts]
    return {
        "facts": {k: int(sum(p["facts"][k] for p in parts)) for k in parts[0]["facts"]},
        "designs": designs_out,
        "backfill_skew": {f: float(np.mean([p["skew"][f] for p in parts])) for f in parts[0]["skew"]},
        "latency_histogram": {"edges_ms": [float(e) for e in edges[:-1]], "counts": lat_hist},
    }


def run(set_name: str, workers: int = 3) -> dict[str, Any]:
    seeds = load("seeds")[set_name]
    fp = config_fingerprint()
    if set_name == "heldout":
        if LOCK.exists():
            raise SystemExit(f"held-out seeds already ran ({LOCK.read_text().strip()}); they run once. See AGENTS.md.")
        REPORTS.mkdir(exist_ok=True)
        LOCK.write_text(json.dumps({"ran_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "config_sha": fp, "seeds": seeds}) + "\n")
    with ProcessPoolExecutor(max_workers=workers) as pool:
        parts = list(pool.map(run_seed, seeds))
    doc = {"set": set_name, "seeds": seeds, "config_sha": fp, "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), **summarize(parts)}
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / f"{set_name}.json").write_text(json.dumps(doc, indent=1, default=float) + "\n")
    return doc
