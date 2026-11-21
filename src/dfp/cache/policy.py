"""When a cached provider response may be served.

A lender's contract or regulator decides how old a bought report may be (bureau: 7 days), and for a
sanctions screen it must post-date the latest list publication. These rules are config
(`config/compliance.yml`); this module only applies them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

DAY = 86400.0


@dataclass(frozen=True)
class FreshnessPolicy:
    max_age_s: float
    stale_if_error_s: float = 0.0
    not_before_daily_hour: int | None = None  # UTC hour of a daily publication the response must follow

    @property
    def cacheable(self) -> bool:
        return self.max_age_s > 0

    def last_publication(self, now: float) -> float | None:
        if self.not_before_daily_hour is None:
            return None
        day_start = math.floor(now / DAY) * DAY
        pub = day_start + self.not_before_daily_hour * 3600
        return pub if pub <= now else pub - DAY

    def fresh(self, fetched_at: float, now: float) -> bool:
        """May this response be served as current?"""
        if not self.cacheable or fetched_at > now:
            return False
        if now - fetched_at > self.max_age_s:
            return False
        pub = self.last_publication(now)
        return pub is None or fetched_at >= pub

    def usable_on_error(self, fetched_at: float, now: float) -> bool:
        """May this response stand in when the provider is failing?"""
        if self.stale_if_error_s <= 0 or fetched_at > now:
            return False
        return now - fetched_at <= self.max_age_s + self.stale_if_error_s

    def store_ttl_s(self) -> float:
        return self.max_age_s + self.stale_if_error_s


def from_rules(rules: dict[str, Any]) -> dict[str, FreshnessPolicy]:
    out = {}
    for provider, r in rules["providers"].items():
        out[provider] = FreshnessPolicy(
            max_age_s=float(r["max_age_hours"]) * 3600,
            stale_if_error_s=float(r.get("stale_if_error_hours", 0)) * 3600,
            not_before_daily_hour=r.get("not_before_daily_hour"),
        )
    return out


def single_ttl(providers: list[str], hours: float) -> dict[str, FreshnessPolicy]:
    """One TTL for every provider: what a generic cache does."""
    return {p: FreshnessPolicy(max_age_s=hours * 3600) for p in providers}
