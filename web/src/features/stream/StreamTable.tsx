import { type DesignRow, pct } from "../../shared/data/report";
import t from "../../shared/ui/table.module.css";

export function StreamTable({ designs, skew }: { designs: Record<string, DesignRow>; skew: Record<string, number> }) {
  const p = designs.platform;
  if (!p) return null;
  return (
    <div className={t.wrap}>
      <table className={t.table}>
        <thead>
          <tr>
            <th>Feature</th>
            <th data-num>This platform</th>
            <th data-num>Counted by arrival, no dedupe</th>
            <th data-num>Platform without dedupe</th>
            <th data-num>Backfill on event time differs from production</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(p.by_feature_exact).map(([f, v]) => (
            <tr key={f}>
              <td>
                <code>{f}</code>
              </td>
              <td data-num>{pct(v, 2)}</td>
              <td data-num>{designs.streaming_naive ? pct(designs.streaming_naive.by_feature_exact[f] ?? 0, 2) : "–"}</td>
              <td data-num>{designs.no_dedupe ? pct(designs.no_dedupe.by_feature_exact[f] ?? 0, 2) : "–"}</td>
              <td data-num>{pct(skew[f] ?? 0, 2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
