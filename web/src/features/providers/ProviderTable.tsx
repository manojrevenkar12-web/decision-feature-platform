import { type ProviderRow, num } from "../../shared/data/report";
import t from "../../shared/ui/table.module.css";

const NAMES: Record<string, string> = {
  bureau: "Credit bureau · reuse 7 days",
  kyb_registry: "Company registry · reuse 30 days",
  sanctions: "Sanctions screen · after the 06:00 list",
  device_risk: "Device risk · never reused",
  open_banking: "Open banking · reuse 1 hour",
};

export function ProviderTable({ rows }: { rows: Record<string, ProviderRow> }) {
  return (
    <div className={t.wrap}>
      <table className={t.table}>
        <thead>
          <tr>
            <th>Provider and the lenders' rule</th>
            <th data-num>Asked for</th>
            <th data-num>Not served</th>
            <th data-num>Report changed since, within the rule</th>
            <th data-num>Rule breaks</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(rows).map(([k, r]) => (
            <tr key={k}>
              <td>{NAMES[k] ?? k}</td>
              <td data-num>{num(r.needed)}</td>
              <td data-num>{num(r.missing)}</td>
              <td data-num>{num(r.changed_within_rule)}</td>
              <td data-num>{num(r.violations)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
