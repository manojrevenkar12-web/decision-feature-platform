import { motion as m, useReducedMotion } from "framer-motion";

import { type DesignRow, MAIN_DESIGNS, eur, ms } from "../../shared/data/report";
import { motion } from "../../shared/theme/motion";
import styles from "./budget.module.css";

const SCALE_MS = 1600;
const BUDGET_MS = 1500;

/** One track per design on the same 0–1,600 ms scale: solid to the median, lighter to p95, lightest to p99. */
export function BudgetTracks({ designs }: { designs: Record<string, DesignRow> }) {
  const reduce = useReducedMotion();
  const rows = MAIN_DESIGNS.filter((k) => designs[k]);
  const at = (x: number) => `${Math.min(x / SCALE_MS, 1) * 100}%`;
  return (
    <figure className={styles.figure} aria-label="Feature latency per decision against the 1,500 ms budget">
      <div className={styles.scale} aria-hidden="true">
        <span style={{ left: "0%" }}>0</span>
        <span style={{ left: at(500) }}>500 ms</span>
        <span style={{ left: at(1000) }}>1,000 ms</span>
        <span className={styles.budget} style={{ left: at(BUDGET_MS) }}>
          budget
        </span>
      </div>
      {rows.map((key, i) => {
        const d = designs[key]!;
        const segments = [
          { to: d.p99_ms[0], tone: "p99" },
          { to: d.p95_ms[0], tone: "p95" },
          { to: d.p50_ms[0], tone: "p50" },
        ];
        return (
          <div key={key} className={styles.row} data-design={key}>
            <p className={styles.name}>{d.label}</p>
            <div className={styles.track}>
              {segments.map((s, j) => (
                <m.span
                  key={s.tone}
                  className={styles.segment}
                  data-tone={s.tone}
                  style={{ width: at(s.to) }}
                  initial={reduce ? false : { scaleX: 0 }}
                  animate={{ scaleX: 1 }}
                  transition={{ duration: motion.base, delay: i * motion.stagger + j * 0.05, ease: motion.ease }}
                />
              ))}
              <span className={styles.budgetLine} style={{ left: at(BUDGET_MS) }} aria-hidden="true" />
            </div>
            <p className={`${styles.values} num`}>
              <span>
                median <strong>{ms(d.p50_ms[0])}</strong>
              </span>
              <span>p95 {ms(d.p95_ms[0])}</span>
              <span>p99 {ms(d.p99_ms[0])}</span>
            </p>
            <p className={`${styles.spend} num`}>
              <strong>{eur(d.spend_per_1k_eur[0])}</strong>
              <span>per 1,000 decisions</span>
            </p>
          </div>
        );
      })}
    </figure>
  );
}
