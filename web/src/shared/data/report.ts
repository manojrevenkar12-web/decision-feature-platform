import { useCallback, useEffect, useState } from "react";

export type SetName = "heldout" | "dev";
export type Interval = [number, number, number];

export interface ProviderRow { needed: number; missing: number; wrong: number; violations: number; changed_within_rule: number }
export interface DesignRow {
  label: string;
  decisions: number;
  p50_ms: Interval;
  p95_ms: Interval;
  p99_ms: Interval;
  spend_per_1k_eur: Interval;
  spend_cut_vs_direct: Interval;
  failed_rate: Interval;
  exact_rate: Interval;
  violations: number;
  cross_tenant: number;
  calls_per_decision: number;
  by_feature_exact: Record<string, number>;
  by_provider: Record<string, ProviderRow>;
  sources: Record<string, number>;
  stream_consumer: { applied: number; duplicates: number; too_late: number; redis_evictions: number };
}
export interface Report {
  set: SetName;
  seeds: number[];
  config_sha: string;
  generated_at: string;
  facts: { events: number; deliveries: number; redelivered: number; late_over_1m: number; decisions: number; customers: number; people_at_two_lenders: number };
  designs: Record<string, DesignRow>;
  backfill_skew: Record<string, number>;
}

export type LoadState = { status: "loading" } | { status: "error"; message: string } | { status: "missing" } | { status: "ready"; report: Report };

/** Loads reports/<set>.json as written by `python -m dfp.cli run`. */
export function useReport(set: SetName): { state: LoadState; retry: () => void } {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    setState({ status: "loading" });
    fetch(`./reports/${set}.json`)
      .then(async (res) => {
        if (!live) return;
        if (res.status === 404) return setState({ status: "missing" });
        if (!res.ok) throw new Error(`The report did not load (HTTP ${res.status}).`);
        const report = (await res.json()) as Report;
        if (live) setState({ status: "ready", report });
      })
      .catch((err: unknown) => live && setState({ status: "error", message: err instanceof Error ? err.message : String(err) }));
    return () => {
      live = false;
    };
  }, [set, attempt]);
  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  return { state, retry };
}

export const MAIN_DESIGNS = ["direct", "ttl_cache", "platform"] as const;

/** A design is flagged when it serves a report the lenders' rules forbid or a stream value that is not exact. */
export function flaw(d: DesignRow): string | null {
  if (d.violations > 0 || d.cross_tenant > 0) return "Breaks a rule";
  if (d.exact_rate[0] < 0.999) return "Miscounts";
  return null;
}

export const pct = (x: number, d = 1) => `${(x * 100).toFixed(d)}%`;
export const num = (x: number) => new Intl.NumberFormat("en-GB").format(Math.round(x));
export const eur = (x: number) => `€${num(x)}`;
export const ms = (x: number) => `${num(x)} ms`;
