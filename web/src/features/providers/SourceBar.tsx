import { pct } from "../../shared/data/report";
import styles from "./providers.module.css";

const ORDER: { key: string; label: string; slot: number }[] = [
  { key: "provider", label: "Paid provider call", slot: 1 },
  { key: "redis", label: "Redis", slot: 2 },
  { key: "dynamodb", label: "DynamoDB", slot: 3 },
  { key: "l1", label: "In-process (L1)", slot: 4 },
  { key: "coalesced", label: "Joined a call in flight", slot: 5 },
  { key: "stale_if_error", label: "Older report while provider failed", slot: 6 },
  { key: "missing", label: "Not served", slot: 7 },
];

/** Where the platform's provider features came from, as one stacked bar with a legend that carries the numbers. */
export function SourceBar({ sources }: { sources: Record<string, number> }) {
  const parts = ORDER.map((o) => ({ ...o, share: sources[o.key] ?? 0 }));
  return (
    <figure className={styles.figure}>
      <div className={styles.bar} role="img" aria-label={parts.map((p) => `${p.label} ${pct(p.share)}`).join(", ")}>
        {parts
          .filter((p) => p.share > 0)
          .map((p) => (
            <span key={p.key} className={styles.part} style={{ flexGrow: p.share, background: `var(--series-${p.slot})` }} />
          ))}
      </div>
      <ul className={styles.legend}>
        {parts.map((p) => (
          <li key={p.key}>
            <span className={styles.swatch} style={{ background: `var(--series-${p.slot})` }} aria-hidden="true" />
            {p.label} <strong className="num">{pct(p.share, p.share < 0.01 ? 2 : 1)}</strong>
          </li>
        ))}
      </ul>
    </figure>
  );
}
