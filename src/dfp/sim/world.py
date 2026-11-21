"""The simulated lenders' world.

Six lenders, their customers' card transactions, the decisions they run and five paid data providers
whose records change over time. Everything random is drawn here, once per seed, so every design
replays the same luck: the same events arriving late, the same Kinesis redeliveries, the same slow
bureau call on decision 41,207, the same Lambda container going cold.

Designs get `Observed` (what the stream delivers, the decisions, the providers' answers, how the AWS
services behave). The hidden part, which events are duplicates and what each provider record really
said at each moment, is read only by `dfp.sim.evaluate` (`tests/test_boundaries.py`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np

from dfp.config import load

PROVIDERS = ("bureau", "kyb_registry", "sanctions", "device_risk", "open_banking")


def _lognormal(rng: np.random.Generator, median: float, sd: float, size: Any) -> np.ndarray:
    return np.asarray(rng.lognormal(np.log(median), sd, size))


def _diurnal_times(rng: np.random.Generator, n: int, start: float, days: int) -> np.ndarray:
    """Event times with a day/night cycle (busiest at 18:00 UTC)."""
    out = np.empty(0)
    while len(out) < n:
        t = rng.uniform(0, days * 86400.0, size=2 * (n - len(out)) + 8)
        hour = (t % 86400) / 3600
        keep = rng.uniform(size=len(t)) < 0.55 + 0.45 * np.cos((hour - 18) / 24 * 2 * np.pi)
        out = np.concatenate([out, t[keep]])
    return np.sort(start + out[:n])


@dataclass
class ProviderLine:
    """What a provider answers when called. It reads the provider's own records, which change
    over time; the platform sees only the response."""

    world: World

    def call(self, provider: str, subject: int, dec: int, attempt: int, t: float) -> tuple[float, bool, dict[str, Any]]:
        w = self.world
        lat = float(w.provider_latency[provider][dec, attempt])
        ok = bool(w.provider_error[provider][dec, attempt] >= w.cfg["providers"][provider]["error_rate"])
        for o in w.cfg["outages"]:
            if o["provider"] == provider:
                lo = w.start + o["day"] * 86400 + o["start_hour"] * 3600
                if lo <= t < lo + o["hours"] * 3600:
                    return 30_000.0, False, {}
        if not ok:
            return lat, False, {}
        if provider == "device_risk":
            return lat, True, {"report_id": f"device_risk-d{dec}", "v": 0, "score": round(float(w.device_score[dec]), 4)}
        v = w.version(provider, subject, t)
        return lat, True, {"report_id": f"{provider}-{subject}-{v}", "v": v}


@dataclass
class Observed:
    """Everything a design may see."""

    start: float
    days: int
    tenants: int
    # what the stream delivers, in delivery order (duplicates included, not marked)
    deliver_time: np.ndarray
    deliver_event: np.ndarray  # index into the event payload arrays
    ev_id: np.ndarray
    ev_cust: np.ndarray
    ev_time: np.ndarray
    ev_amount: np.ndarray
    ev_merchant: np.ndarray
    ev_declined: np.ndarray
    # customers as the lender knows them
    cust_tenant: np.ndarray
    cust_person: np.ndarray  # the national ID / company number a provider is asked about
    cust_business: np.ndarray
    # decisions in time order
    dec_time: np.ndarray
    dec_cust: np.ndarray
    dec_open_banking: np.ndarray
    providers: ProviderLine
    provider_cost: dict[str, float]
    # how AWS behaves for each decision (same for every design)
    redis_ms: np.ndarray
    dynamo_ms: np.ndarray
    aurora_ms: np.ndarray
    container: np.ndarray
    cold_ms: np.ndarray
    recycle: list[np.ndarray]
    infra: dict[str, Any]


@dataclass
class World:
    seed: int
    cfg: dict[str, Any]
    start: float
    days: int
    cust_tenant: np.ndarray
    cust_person: np.ndarray
    cust_business: np.ndarray
    ev_cust: np.ndarray
    ev_time: np.ndarray
    ev_arrival: np.ndarray
    ev_amount: np.ndarray
    ev_merchant: np.ndarray
    ev_declined: np.ndarray
    deliver_time: np.ndarray
    deliver_event: np.ndarray
    dec_time: np.ndarray
    dec_cust: np.ndarray
    dec_open_banking: np.ndarray
    changes: dict[str, list[np.ndarray]]
    provider_latency: dict[str, np.ndarray]
    provider_error: dict[str, np.ndarray]
    device_score: np.ndarray
    redis_ms: np.ndarray
    dynamo_ms: np.ndarray
    aurora_ms: np.ndarray
    container: np.ndarray
    cold_ms: np.ndarray
    recycle: list[np.ndarray]
    _line: ProviderLine | None = field(default=None, repr=False)

    def version(self, provider: str, person: int, t: float) -> int:
        """Hidden: how many times this person's record at this provider has changed by t."""
        return int(np.searchsorted(self.changes[provider][person], t, side="right"))

    def observed(self) -> Observed:
        if self._line is None:
            self._line = ProviderLine(self)
        return Observed(
            start=self.start,
            days=self.days,
            tenants=int(self.cfg["tenants"]),
            deliver_time=self.deliver_time,
            deliver_event=self.deliver_event,
            ev_id=np.arange(len(self.ev_time)),
            ev_cust=self.ev_cust,
            ev_time=self.ev_time,
            ev_amount=self.ev_amount,
            ev_merchant=self.ev_merchant,
            ev_declined=self.ev_declined,
            cust_tenant=self.cust_tenant,
            cust_person=self.cust_person,
            cust_business=self.cust_business,
            dec_time=self.dec_time,
            dec_cust=self.dec_cust,
            dec_open_banking=self.dec_open_banking,
            providers=self._line,
            provider_cost={p: float(self.cfg["providers"][p]["cost_eur"]) for p in PROVIDERS},
            redis_ms=self.redis_ms,
            dynamo_ms=self.dynamo_ms,
            aurora_ms=self.aurora_ms,
            container=self.container,
            cold_ms=self.cold_ms,
            recycle=self.recycle,
            infra=self.cfg["infrastructure"],
        )


def simulate(seed: int, cfg: dict[str, Any] | None = None) -> World:
    cfg = cfg or load("world")
    ss = np.random.SeedSequence(seed)
    r_people, r_dec, r_ev, r_arr, r_prov, r_infra = (np.random.default_rng(s) for s in ss.spawn(6))
    days = int(cfg["days"])
    start = datetime.fromisoformat(cfg["start"].replace("Z", "+00:00")).timestamp()
    horizon = days * 86400.0

    # customers and the people behind them
    n_t, per = int(cfg["tenants"]), int(cfg["customers_per_tenant"])
    cust_tenant = np.repeat(np.arange(n_t), per)
    cust_person = np.empty(n_t * per, dtype=np.int64)
    next_person = 0
    for i in range(len(cust_tenant)):
        others = np.flatnonzero(cust_tenant[:i] != cust_tenant[i])
        if len(others) and r_people.uniform() < cfg["shared_person_share"]:
            cust_person[i] = cust_person[r_people.choice(others)]
        else:
            cust_person[i] = next_person
            next_person += 1
    n_people = next_person
    person_business = r_people.uniform(size=n_people) < cfg["business_share"]
    cust_business = person_business[cust_person]
    n_c = len(cust_tenant)

    # decisions, with double submits
    d = cfg["decisions"]
    counts = r_dec.poisson(d["per_customer_per_day"] * days, size=n_c)
    times, custs = [], []
    for c in range(n_c):
        ts = _diurnal_times(r_dec, int(counts[c]), start, days)
        for t in ts:
            times.append(t)
            custs.append(c)
            if r_dec.uniform() < d["resubmit_share"]:
                for _ in range(int(r_dec.integers(d["resubmit_extra"][0], d["resubmit_extra"][1] + 1))):
                    times.append(t + r_dec.uniform(0.02, d["resubmit_within_s"]))
                    custs.append(c)
    order = np.argsort(times, kind="stable")
    dec_time = np.asarray(times)[order]
    dec_cust = np.asarray(custs, dtype=np.int64)[order]
    keep = dec_time < start + horizon
    dec_time, dec_cust = dec_time[keep], dec_cust[keep]
    n_d = len(dec_time)
    dec_open_banking = r_dec.uniform(size=n_d) < d["open_banking_share"]

    # transactions
    tx = cfg["transactions"]
    rate = tx["mean_per_day"] * r_ev.gamma(tx["heterogeneity_shape"], 1 / tx["heterogeneity_shape"], size=n_c)
    favourites = [np.minimum(r_ev.zipf(tx["merchant_zipf"], size=int(r_ev.integers(5, 30))), tx["merchants"]) for _ in range(n_c)]
    ev_cust_l, ev_time_l, ev_decl_rate = [], [], []
    for c in range(n_c):
        n = int(r_ev.poisson(rate[c] * days))
        ev_time_l.append(_diurnal_times(r_ev, n, start, days))
        ev_cust_l.append(np.full(n, c))
        ev_decl_rate.append(np.full(n, tx["decline_rate"]))
    burst_cust = np.flatnonzero(r_ev.uniform(size=n_c) < tx["burst_share"])
    for c in burst_cust.tolist():
        mine = np.flatnonzero(dec_cust == c)
        if not len(mine):
            continue
        t_dec = dec_time[r_ev.choice(mine)]
        end = t_dec - r_ev.uniform(*d["burst_decision_lag_s"])
        n = int(r_ev.integers(tx["burst_events"][0], tx["burst_events"][1] + 1))
        ev_time_l.append(np.sort(end - r_ev.uniform(0, tx["burst_minutes"] * 60, size=n)))
        ev_cust_l.append(np.full(n, c))
        ev_decl_rate.append(np.full(n, tx["burst_decline_rate"]))
    ev_time = np.concatenate(ev_time_l)
    ev_cust = np.concatenate(ev_cust_l).astype(np.int64)
    decl_p = np.concatenate(ev_decl_rate)
    order = np.argsort(ev_time, kind="stable")
    ev_time, ev_cust, decl_p = ev_time[order], ev_cust[order], decl_p[order]
    n_e = len(ev_time)
    ev_amount = np.round(np.exp(r_ev.normal(tx["amount_log_mean"], tx["amount_log_sd"], size=n_e)) * 100).astype(np.int64)
    ev_declined = r_ev.uniform(size=n_e) < decl_p
    fav_pick = r_ev.uniform(size=n_e) < 0.8
    glob = np.minimum(r_ev.zipf(tx["merchant_zipf"], size=n_e), tx["merchants"])
    ev_merchant = np.array([favourites[c][r_ev.integers(len(favourites[c]))] if f else g for c, f, g in zip(ev_cust, fav_pick, glob, strict=True)], dtype=np.int64)

    # arrival at the stream, and redeliveries
    a = cfg["arrival"]
    kind = r_arr.choice(3, size=n_e, p=[a["fast"]["share"], a["slow"]["share"], a["offline"]["share"]])
    delay = np.empty(n_e)
    for k, name in enumerate(("fast", "slow", "offline")):
        m = kind == k
        delay[m] = _lognormal(r_arr, a[name]["median_s"], a[name]["sd"], int(m.sum()))
    ev_arrival = ev_time + delay
    again = np.flatnonzero(r_arr.uniform(size=n_e) < a["redelivery_rate"])
    deliver_time = np.concatenate([ev_arrival, ev_arrival[again] + r_arr.uniform(*a["redelivery_delay_s"], size=len(again))])
    deliver_event = np.concatenate([np.arange(n_e), again])
    order = np.argsort(deliver_time, kind="stable")
    deliver_time, deliver_event = deliver_time[order], deliver_event[order]

    # providers: when each person's record changes, and the luck of every call
    pc = cfg["providers"]
    changes: dict[str, list[np.ndarray]] = {}
    for p in PROVIDERS:
        spec = pc[p]
        if p == "device_risk":
            changes[p] = []
        elif p == "sanctions":
            pubs = start + np.arange(-1, days + 1) * 86400.0 + spec["publish_hour"] * 3600
            hit = r_prov.uniform(size=(n_people, len(pubs))) < spec["change_per_publish"]
            changes[p] = [pubs[hit[i]] for i in range(n_people)]
        else:
            lam = horizon / (spec["change_every_days"] * 86400.0)
            changes[p] = [np.sort(start - 30 * 86400 + r_prov.uniform(0, horizon + 30 * 86400, size=r_prov.poisson(lam * (1 + 30 / days)))) for _ in range(n_people)]
    provider_latency = {p: _lognormal(r_prov, pc[p]["latency_median_ms"], pc[p]["latency_sd"], (n_d, 2)) for p in PROVIDERS}
    provider_error = {p: r_prov.uniform(size=(n_d, 2)) for p in PROVIDERS}
    device_score = r_prov.beta(2, 8, size=n_d)

    # AWS
    inf = cfg["infrastructure"]
    redis_ms = _lognormal(r_infra, inf["redis"]["median_ms"], inf["redis"]["sd"], (n_d, 6))
    dynamo_ms = _lognormal(r_infra, inf["dynamodb"]["median_ms"], inf["dynamodb"]["sd"], (n_d, 6))
    aurora_ms = _lognormal(r_infra, inf["aurora"]["median_ms"], inf["aurora"]["sd"], n_d)
    n_ct = int(inf["warm_containers"])
    container = r_infra.integers(0, n_ct, size=n_d)
    cold_ms = r_infra.uniform(*inf["cold_start_ms"], size=n_d)
    lo, hi = inf["container_life_minutes"]
    recycle = [start + np.cumsum(r_infra.uniform(lo * 60, hi * 60, size=int(horizon / (lo * 60)) + 2)) for _ in range(n_ct)]

    return World(
        seed=seed,
        cfg=cfg,
        start=start,
        days=days,
        cust_tenant=cust_tenant,
        cust_person=cust_person,
        cust_business=cust_business,
        ev_cust=ev_cust,
        ev_time=ev_time,
        ev_arrival=ev_arrival,
        ev_amount=ev_amount,
        ev_merchant=ev_merchant,
        ev_declined=ev_declined,
        deliver_time=deliver_time,
        deliver_event=deliver_event,
        dec_time=dec_time,
        dec_cust=dec_cust,
        dec_open_banking=dec_open_banking,
        changes=changes,
        provider_latency=provider_latency,
        provider_error=provider_error,
        device_score=device_score,
        redis_ms=redis_ms,
        dynamo_ms=dynamo_ms,
        aurora_ms=aurora_ms,
        container=container,
        cold_ms=cold_ms,
        recycle=recycle,
    )
