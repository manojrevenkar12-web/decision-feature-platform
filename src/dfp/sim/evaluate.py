"""Grades what each design served against the world's hidden truth. The only module that reads
`World` beyond `observed()`."""

from __future__ import annotations

from typing import Any

import numpy as np

from dfp.cache.policy import from_rules
from dfp.config import load
from dfp.features.spec import FeatureSet
from dfp.offline import pit
from dfp.sim.designs import SRC, Served
from dfp.sim.world import PROVIDERS, World


def _unique_by_customer(w: World) -> dict[int, np.ndarray]:
    order = np.argsort(w.ev_cust, kind="stable")
    bounds = np.searchsorted(w.ev_cust[order], np.arange(len(w.cust_tenant) + 1))
    return {c: order[bounds[c] : bounds[c + 1]] for c in range(len(w.cust_tenant))}


def truth_stream(w: World, features: FeatureSet) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    """Per decision: the value knowable at the gate (each event once, arrived by t), and what a
    backfill filtering on event time alone would compute."""
    idx = _unique_by_customer(w)
    n = len(w.dec_time)
    known = {f.name: np.zeros(n) for f in features.stream}
    leak = {f.name: np.zeros(n) for f in features.stream}
    for i in range(n):
        ix = idx[int(w.dec_cust[i])]
        t = float(w.dec_time[i])
        et, ar, am, dc, me = w.ev_time[ix], w.ev_arrival[ix], w.ev_amount[ix], w.ev_declined[ix], w.ev_merchant[ix]
        for f in features.stream:
            known[f.name][i] = pit.as_of(f, t, et, ar, am, dc, me)
            leak[f.name][i] = pit.leaky(f, t, et, am, dc, me)
    return known, leak


def truth_versions(w: World) -> dict[str, np.ndarray]:
    person = w.cust_person[w.dec_cust]
    out = {}
    for p in PROVIDERS:
        if p == "device_risk":
            out[p] = np.zeros(len(w.dec_time), dtype=np.int64)
        else:
            out[p] = np.array([w.version(p, int(pp), float(t)) for pp, t in zip(person, w.dec_time, strict=True)], dtype=np.int64)
    return out


def grade(w: World, s: Served, known: dict[str, np.ndarray], versions: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Per-decision outcomes for one design."""
    rules = load("compliance")
    policies = from_rules(rules)
    tenant = w.cust_tenant[w.dec_cust]
    n = len(w.dec_time)
    exact = np.ones(n, dtype=bool)
    per_feature = {}
    for name, truth in known.items():
        ok = np.isclose(s.stream[name], truth, rtol=0, atol=1e-9)
        per_feature[name] = ok
        exact &= ok
    wrong = np.zeros(n, dtype=np.int64)
    violations = np.zeros(n, dtype=np.int64)
    cross = np.zeros(n, dtype=np.int64)
    served_n = np.zeros(n, dtype=np.int64)
    by_provider: dict[str, np.ndarray] = {}
    for p in PROVIDERS:
        served = s.version[p] >= 0
        served_n += served
        wr = served & (s.version[p] != versions[p])
        wrong += wr
        pol = policies[p]
        # a report fetched for this decision (or by a concurrent one it joined) is current by definition
        fresh = np.array([(not ok) or fa >= t or pol.fresh(fa, t) for fa, t, ok in zip(s.fetched_at[p], w.dec_time, served, strict=True)])
        stale_ok = (s.source[p] == SRC["stale_if_error"]) & np.array(
            [pol.usable_on_error(fa, t) if ok else False for fa, t, ok in zip(s.fetched_at[p], w.dec_time, served, strict=True)]
        )
        viol = served & ~fresh & ~stale_ok
        violations += viol
        x = served & (s.paid_by[p] != tenant) if not rules["cross_tenant_reuse"] else np.zeros(n, dtype=bool)
        cross += x
        by_provider[f"wrong_{p}"] = wr
        by_provider[f"changed_within_rule_{p}"] = wr & ~viol
        by_provider[f"violation_{p}"] = viol
        by_provider[f"needed_{p}"] = s.needed[p]
        by_provider[f"served_{p}"] = served
    out: dict[str, np.ndarray] = {
        "latency_ms": s.latency_ms,
        "cost_eur": s.cost_eur,
        "calls": s.calls,
        "failed": s.failed,
        "failed_missing": s.failed_missing,
        "cold": s.cold,
        "exact": exact,
        "wrong_reports": wrong,
        "served_reports": served_n,
        "violations": violations,
        "cross_tenant": cross,
        **{f"exact_{k}": v for k, v in per_feature.items()},
        **by_provider,
    }
    for src, code in SRC.items():
        tot = np.zeros(n, dtype=np.int64)
        for p in PROVIDERS:
            tot += s.needed[p] & (s.source[p] == code)
        out[f"src_{src}"] = tot
    return out


def blocks(w: World) -> np.ndarray:
    """Day index of each decision: the unit the bootstrap resamples."""
    return ((w.dec_time - w.start) // 86400).astype(np.int64)


def bootstrap(stat: Any, groups: list[np.ndarray], reps: int = 400, seed: int = 0) -> tuple[float, float, float]:
    """Point estimate and 95% interval of stat(indices) when whole days are resampled."""
    rng = np.random.default_rng(seed)
    est = float(stat(np.concatenate(groups)))
    vals = []
    for _ in range(reps):
        pick = rng.integers(0, len(groups), size=len(groups))
        vals.append(stat(np.concatenate([groups[k] for k in pick])))
    lo, hi = np.percentile(vals, [2.5, 97.5])
    return est, float(lo), float(hi)


def summarize(graded: dict[str, list[dict[str, np.ndarray]]], days: list[np.ndarray], labels: dict[str, str]) -> dict[str, Any]:
    """`graded[design]` holds one dict per seed; `days[k]` the day index of seed k's decisions."""
    groups: list[np.ndarray] = []
    offset = 0
    for d in days:
        for day in np.unique(d):
            groups.append(offset + np.flatnonzero(d == day))
        offset += len(d)

    def cat(design: str, key: str) -> np.ndarray:
        return np.concatenate([g[key] for g in graded[design]])

    out: dict[str, Any] = {}
    direct_cost = cat("direct", "cost_eur") if "direct" in graded else None
    for design in graded:
        lat = cat(design, "latency_ms")
        cost = cat(design, "cost_eur")
        row: dict[str, Any] = {"label": labels[design], "decisions": int(len(lat))}
        for q in (50, 95, 99):
            row[f"p{q}_ms"] = bootstrap(lambda ix, q=q, lat=lat: float(np.percentile(lat[ix], q)), groups)
        row["spend_per_1k_eur"] = bootstrap(lambda ix, cost=cost: float(cost[ix].mean() * 1000), groups)
        if direct_cost is not None:
            row["spend_cut_vs_direct"] = bootstrap(lambda ix, cost=cost, base=direct_cost: float(1 - cost[ix].sum() / base[ix].sum()), groups)
        for k in ("failed", "failed_missing", "exact", "cold"):
            v = cat(design, k).astype(float)
            row[f"{k}_rate"] = bootstrap(lambda ix, v=v: float(v[ix].mean()), groups)
        served = cat(design, "served_reports")
        for k in ("wrong_reports", "violations", "cross_tenant"):
            v = cat(design, k)
            row[k] = int(v.sum())
            row[f"{k}_rate"] = bootstrap(lambda ix, v=v, served=served: float(v[ix].sum() / max(served[ix].sum(), 1)), groups)
        row["calls_per_decision"] = float(cat(design, "calls").mean())
        row["by_feature_exact"] = {k[6:]: float(cat(design, k).mean()) for k in graded[design][0] if k.startswith("exact_")}
        row["by_provider"] = {}
        for p in PROVIDERS:
            need = cat(design, f"needed_{p}")
            srv = cat(design, f"served_{p}")
            row["by_provider"][p] = {
                "needed": int(need.sum()),
                "missing": int((need & ~srv).sum()),
                "wrong": int(cat(design, f"wrong_{p}").sum()),
                "violations": int(cat(design, f"violation_{p}").sum()),
                "changed_within_rule": int(cat(design, f"changed_within_rule_{p}").sum()),
            }
        total_needed = sum(row["by_provider"][p]["needed"] for p in PROVIDERS)
        row["sources"] = {k[4:]: float(cat(design, k).sum() / total_needed) for k in graded[design][0] if k.startswith("src_")}
        out[design] = row
    return out
