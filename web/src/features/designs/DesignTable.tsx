import { type DesignRow, eur, flaw, num, pct } from "../../shared/data/report";
import t from "../../shared/ui/table.module.css";
import styles from "./designs.module.css";

/** Every design on the same decisions, sorted by spend; flawed designs say why. */
export function DesignTable({ designs }: { designs: Record<string, DesignRow> }) {
  const keys = Object.keys(designs).sort((a, b) => designs[a]!.spend_per_1k_eur[0] - designs[b]!.spend_per_1k_eur[0]);
  return (
    <div className={t.wrap}>
      <table className={t.table}>
        <thead>
          <tr>
            <th>Design</th>
            <th data-num>Spend per 1,000</th>
            <th data-num>p50 / p95 / p99</th>
            <th data-num>Referred</th>
            <th data-num>Stream exact</th>
            <th data-num>Rule breaks</th>
            <th data-num>Served to another lender</th>
          </tr>
        </thead>
        <tbody>
          {keys.map((k) => {
            const d = designs[k]!;
            const issue = flaw(d);
            return (
              <tr key={k} data-current={k === "platform" ? "" : undefined}>
                <td>
                  {d.label}
                  {issue && <span className={styles.flag}>{issue}</span>}
                </td>
                <td data-num>
                  {eur(d.spend_per_1k_eur[0])}
                  <span className={t.sub}>
                    {num(d.spend_per_1k_eur[1])}–{num(d.spend_per_1k_eur[2])}
                  </span>
                </td>
                <td data-num>
                  {num(d.p50_ms[0])} / {num(d.p95_ms[0])} / {num(d.p99_ms[0])} ms
                </td>
                <td data-num>{pct(d.failed_rate[0], 2)}</td>
                <td data-num>{pct(d.exact_rate[0], 1)}</td>
                <td data-num>{num(d.violations)}</td>
                <td data-num>{num(d.cross_tenant)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
