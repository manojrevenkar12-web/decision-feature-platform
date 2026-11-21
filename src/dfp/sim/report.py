"""Generated reports: REPORT.md, the figures in docs/figures, the dashboard's data and the results
block in README.md. Nothing here is edited by hand; run `python -m dfp.cli report` after a run."""

from __future__ import annotations

import json
import re
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from dfp.config import ROOT  # noqa: E402

REPORTS = ROOT / "reports"
FIGS = ROOT / "docs" / "figures"
BLUE, ORANGE, AQUA, GREY, INK, MUTED, GRID = "#2a78d6", "#eb6834", "#1baf7a", "#a3a29c", "#0b0b0b", "#52514e", "#e6e5e0"
PROVIDER_NAMES = {
    "bureau": "Credit bureau",
    "kyb_registry": "Company registry (KYB)",
    "sanctions": "Sanctions screen",
    "device_risk": "Device risk",
    "open_banking": "Open banking",
}


def load(name: str) -> dict[str, Any] | None:
    p = REPORTS / f"{name}.json"
    return json.loads(p.read_text()) if p.exists() else None


def pct(x: float, d: int = 1) -> str:
    return f"{x * 100:.{d}f}%"


def ci_pct(v: list[float], d: int = 1) -> str:
    return f"{pct(v[0], d)} ({pct(v[1], d)}–{pct(v[2], d)})"


def ci_eur(v: list[float]) -> str:
    return f"€{v[0]:,.0f} ({v[1]:,.0f}–{v[2]:,.0f})"


def breaks_rules(r: dict[str, Any]) -> bool:
    """Serves a report the lenders' rules forbid, or stream features that are not exact."""
    return bool(r["violations"] or r["cross_tenant"] or r["exact_rate"][0] < 0.999)


def headline(doc: dict[str, Any]) -> str:
    d = doc["designs"]
    p, x, t, n = d["platform"], d["direct"], d["ttl_cache"], d["streaming_naive"]
    return (
        f"Against querying every source on every decision, the platform cut provider spend by "
        f"**{pct(p['spend_cut_vs_direct'][0], 0)}** (95% interval {pct(p['spend_cut_vs_direct'][1], 0)}–{pct(p['spend_cut_vs_direct'][2], 0)}), "
        f"from €{x['spend_per_1k_eur'][0]:,.0f} to €{p['spend_per_1k_eur'][0]:,.0f} per 1,000 decisions, and median feature latency from "
        f"{x['p50_ms'][0]:,.0f} ms to {p['p50_ms'][0]:,.0f} ms, while serving every stream feature exactly and no report the lenders' rules forbid. "
        f"A generic 24-hour Redis cache saves less ({pct(t['spend_cut_vs_direct'][0], 0)}) and breaks those rules "
        f"{t['violations']:,} times, plus {t['cross_tenant']:,} reports served to a lender that did not buy them. "
        f"Counting the stream by arrival time without dedupe gets {pct(1 - n['exact_rate'][0], 1)} of decisions' stream features wrong."
    )


def tables(doc: dict[str, Any]) -> str:
    f, d = doc["facts"], doc["designs"]
    lines = [
        f"Seeds {', '.join(map(str, doc['seeds']))} · {f['decisions']:,} decisions · {f['events']:,} card transactions "
        f"({f['redelivered']:,} delivered twice, {f['late_over_1m']:,} more than a minute late) · {f['customers']:,} customers at 6 lenders · "
        f"config `{doc['config_sha']}`. Intervals are 95%, resampling whole days.",
        "",
        "| Design | Spend per 1,000 decisions | p50 / p95 / p99 | Decisions referred | Stream features exact | Rule breaks | Reports served to another lender |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, r in d.items():
        bold = "**" if name == "platform" else ""
        lines.append(
            f"| {bold}{r['label']}{bold} | {ci_eur(r['spend_per_1k_eur'])} | {r['p50_ms'][0]:,.0f} / {r['p95_ms'][0]:,.0f} / {r['p99_ms'][0]:,.0f} ms | "
            f"{ci_pct(r['failed_rate'], 2)} | {ci_pct(r['exact_rate'], 1)} | {r['violations']:,} | {r['cross_tenant']:,} |"
        )
    p = d["platform"]
    lines += [
        "",
        "**Where the platform's provider features came from**: "
        + ", ".join(f"{k.replace('_', ' ')} {pct(v, 1)}" for k, v in sorted(p["sources"].items(), key=lambda kv: -kv[1]) if v > 0)
        + ".",
        "",
        "| Provider | Asked for | Not served | Served a report that changed since, within the lender's rule | Rule breaks |",
        "|---|---|---|---|---|",
    ]
    for prov, r in p["by_provider"].items():
        lines.append(f"| {PROVIDER_NAMES[prov]} | {r['needed']:,} | {r['missing']:,} | {r['changed_within_rule']:,} | {r['violations']:,} |")
    lines += [
        "",
        "| Stream feature | Platform exact | Arrival-time counters, no dedupe | Platform without dedupe | Backfill on event time differs from what production served |",
        "|---|---|---|---|---|",
    ]
    for feat, v in p["by_feature_exact"].items():
        lines.append(
            f"| `{feat}` | {pct(v, 2)} | {pct(d['streaming_naive']['by_feature_exact'][feat], 2)} | "
            f"{pct(d['no_dedupe']['by_feature_exact'][feat], 2)} | {pct(doc['backfill_skew'][feat], 2)} |"
        )
    c = p["stream_consumer"]
    lines += ["", f"The platform's consumer applied {c['applied']:,} events and dropped {c['duplicates']:,} redeliveries."]
    return "\n".join(lines)


def _style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9,
            "axes.edgecolor": GRID,
            "axes.labelcolor": MUTED,
            "xtick.color": MUTED,
            "ytick.color": INK,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.spines.left": False,
        }
    )


def figures(doc: dict[str, Any]) -> None:
    FIGS.mkdir(parents=True, exist_ok=True)
    _style()
    d = doc["designs"]
    names = sorted(d, key=lambda k: d[k]["spend_per_1k_eur"][0])
    fig, ax = plt.subplots(figsize=(8.2, 4.2), dpi=160)
    for i, n in enumerate(names):
        r = d[n]
        col = BLUE if n == "platform" else (ORANGE if breaks_rules(r) else GREY)
        est, lo, hi = r["spend_per_1k_eur"]
        ax.barh(i, est, color=col, height=0.62)
        ax.plot([lo, hi], [i, i], color=INK, lw=1)
        ax.text(hi + 12, i, f"€{est:,.0f}", va="center", color=INK, fontsize=8.5)
    ax.set_yticks(range(len(names)), [d[n]["label"] for n in names])
    ax.grid(axis="x", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    ax.set_xlabel("Provider spend per 1,000 decisions (€), with 95% interval")
    ax.set_xlim(0, max(d[n]["spend_per_1k_eur"][2] for n in names) * 1.15)
    from matplotlib.patches import Patch

    ax.legend(
        handles=[
            Patch(color=BLUE, label="This platform"),
            Patch(color=GREY, label="Correct and within the rules"),
            Patch(color=ORANGE, label="Breaks a rule or miscounts"),
        ],
        loc="lower right",
        frameon=False,
    )
    ax.set_title("Spend per 1,000 decisions", loc="left", color=INK, fontsize=11)
    fig.tight_layout()
    fig.savefig(FIGS / "spend-by-design.png", bbox_inches="tight")
    plt.close(fig)

    h = doc["latency_histogram"]
    edges = h["edges_ms"]
    fig, ax = plt.subplots(figsize=(8.2, 3.6), dpi=160)
    for n, col in (("direct", GREY), ("ttl_cache", ORANGE), ("platform", BLUE)):
        counts = h["counts"][n]
        total = sum(counts)
        cum, ys = 0, []
        for c in counts:
            cum += c
            ys.append(cum / total * 100)
        # share served within each bin's right edge; the last bin holds everything over budget
        ax.step([0.0, *edges[1:], 1600.0], [0.0, *ys], where="post", color=col, lw=2, label=d[n]["label"])
    ax.axvline(1500, color=MUTED, lw=1, ls="--")
    ax.text(1490, 60, "budget 1,500 ms", ha="right", color=MUTED, fontsize=8)
    ax.set_xlim(0, 1600)
    ax.set_ylim(0, 101)
    ax.set_xlabel("Feature latency per decision (ms)")
    ax.set_ylabel("Decisions served within (%)")
    ax.grid(color=GRID, lw=0.8)
    ax.spines["left"].set_visible(True)
    ax.legend(frameon=False, loc="lower right", bbox_to_anchor=(0.9, 0.04))
    ax.set_title("How fast decisions got their features", loc="left", color=INK, fontsize=11)
    fig.tight_layout()
    fig.savefig(FIGS / "latency-cdf.png", bbox_inches="tight")
    plt.close(fig)


def _inject(path: Any, block: str) -> None:
    text = path.read_text()
    new = re.sub(r"<!-- results:start -->.*<!-- results:end -->", f"<!-- results:start -->\n{block}\n<!-- results:end -->", text, flags=re.S)
    path.write_text(new)


def write() -> None:
    dev, held = load("dev"), load("heldout")
    main = held or dev
    if main is None:
        raise SystemExit("no reports yet: run `python -m dfp.cli run dev` first")
    which = "held-out" if held else "development"
    figures(main)
    body = [
        "# Results",
        "",
        "Generated by `python -m dfp.cli report` from `reports/*.json`. Do not edit.",
        "",
        f"## {which.capitalize()} seeds",
        "",
        headline(main),
        "",
        tables(main),
    ]
    if held and dev:
        body += ["", "## Development seeds", "", tables(dev)]
    (ROOT / "REPORT.md").write_text("\n".join(body) + "\n")
    block = "\n".join(
        [
            f"_From the {which} seeds ({', '.join(map(str, main['seeds']))}), run once; generated by `python -m dfp.cli report`._",
            "",
            headline(main),
            "",
            "![Spend per 1,000 decisions by design](docs/figures/spend-by-design.png)",
            "",
            tables(main),
            "",
            "![Share of decisions served within a latency](docs/figures/latency-cdf.png)",
        ]
    )
    readme = ROOT / "README.md"
    if readme.exists():
        _inject(readme, block)


def gate(doc: dict[str, Any], gates: dict[str, Any]) -> list[str]:
    g, d = gates["platform"], doc["designs"]
    p = d["platform"]
    fails = []
    if p["exact_rate"][0] < g["stream_exact_min"]:
        fails.append(f"stream exact {p['exact_rate'][0]:.4f} < {g['stream_exact_min']}")
    if p["violations"] > g["policy_violations_max"]:
        fails.append(f"{p['violations']} rule breaks")
    if p["cross_tenant"] > g["cross_tenant_reuse_max"]:
        fails.append(f"{p['cross_tenant']} cross-tenant reuses")
    if p["p99_ms"][0] > g["p99_ms_max"]:
        fails.append(f"p99 {p['p99_ms'][0]:.0f} ms > {g['p99_ms_max']}")
    if p["spend_cut_vs_direct"][1] < g["spend_cut_vs_direct_low_min"]:
        fails.append(f"spend cut low end {p['spend_cut_vs_direct'][1]:.3f} < {g['spend_cut_vs_direct_low_min']}")
    if p["failed_rate"][0] > g["failed_rate_max"]:
        fails.append(f"failed rate {p['failed_rate'][0]:.4f} > {g['failed_rate_max']}")
    if g.get("fails_less_than_direct") and p["failed_rate"][0] >= d["direct"]["failed_rate"][0]:
        fails.append("platform refers as many decisions as the status quo")
    return fails
