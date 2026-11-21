"""Feature definitions. A stream feature aggregates a customer's transactions over a minute-aligned
window; a provider feature comes from a paid third-party call."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Agg = Literal["count", "sum", "distinct", "declined_ratio"]
AGGS: tuple[str, ...] = ("count", "sum", "distinct", "declined_ratio")


@dataclass(frozen=True)
class StreamFeature:
    name: str
    agg: Agg
    window_minutes: int

    def __post_init__(self) -> None:
        if self.agg not in AGGS:
            raise ValueError(f"{self.name}: unknown aggregation {self.agg!r}")
        if self.window_minutes < 1:
            raise ValueError(f"{self.name}: window must be at least one minute")


@dataclass(frozen=True)
class ProviderFeature:
    name: str
    provider: str
    only_business: bool = False
    optional_share: bool = False


@dataclass(frozen=True)
class FeatureSet:
    stream: tuple[StreamFeature, ...]
    provider: tuple[ProviderFeature, ...]

    @property
    def longest_window(self) -> int:
        return max(f.window_minutes for f in self.stream)

    def names(self) -> list[str]:
        return [f.name for f in self.stream] + [f.name for f in self.provider]

    def get_stream(self, name: str) -> StreamFeature:
        for f in self.stream:
            if f.name == name:
                return f
        raise KeyError(name)


def parse(doc: dict[str, Any]) -> FeatureSet:
    stream = tuple(StreamFeature(name=n, agg=s["agg"], window_minutes=int(s["window_minutes"])) for n, s in doc["stream"].items())
    provider = tuple(
        ProviderFeature(
            name=n,
            provider=s["provider"],
            only_business=bool(s.get("only_business", False)),
            optional_share=bool(s.get("optional_share", False)),
        )
        for n, s in doc["provider"].items()
    )
    names = [f.name for f in stream] + [f.name for f in provider]
    if len(set(names)) != len(names):
        raise ValueError("feature names must be unique")
    return FeatureSet(stream=stream, provider=provider)
