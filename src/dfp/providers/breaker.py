"""A circuit breaker per provider. After a run of failures it opens and calls fail fast instead of
waiting out the timeout; after a cooldown one call is let through to probe."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Breaker:
    failures_to_open: int = 5
    cooldown_s: float = 30.0
    consecutive: int = 0
    opened_at: float | None = None
    probing: bool = False

    def allow(self, now: float) -> bool:
        if self.opened_at is None:
            return True
        if now - self.opened_at >= self.cooldown_s and not self.probing:
            self.probing = True
            return True
        return False

    def record(self, ok: bool, now: float) -> None:
        if ok:
            self.consecutive = 0
            self.opened_at = None
            self.probing = False
            return
        self.consecutive += 1
        if self.probing or self.consecutive >= self.failures_to_open:
            self.opened_at = now
            self.probing = False

    @property
    def open(self) -> bool:
        return self.opened_at is not None
