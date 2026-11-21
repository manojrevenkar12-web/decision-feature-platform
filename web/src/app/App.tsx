import { AnimatePresence, motion as m } from "framer-motion";
import { useState } from "react";

import { BudgetTracks } from "../features/budget/BudgetTracks";
import { DesignTable } from "../features/designs/DesignTable";
import { ProviderTable } from "../features/providers/ProviderTable";
import { SourceBar } from "../features/providers/SourceBar";
import { StreamTable } from "../features/stream/StreamTable";
import { type Report, type SetName, num, pct, useReport } from "../shared/data/report";
import { motion } from "../shared/theme/motion";
import { ErrorState, MissingState, Skeleton } from "../shared/ui/states";
import styles from "./App.module.css";

const SETS: { key: SetName; label: string }[] = [
  { key: "heldout", label: "Held-out seeds" },
  { key: "dev", label: "Development seeds" },
];

export function App() {
  const [set, setSet] = useState<SetName>("heldout");
  const { state, retry } = useReport(set);
  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <h1 className={styles.title}>Features for a credit decision, inside 1,500 ms</h1>
          <p className={styles.lede}>
            Six simulated lenders, their customers' card transactions and five paid data providers. Each design serves the same decisions with the
            same luck; the world grades them against what was really knowable and what the lenders' rules allow.
          </p>
        </div>
        <div className={styles.switch} role="group" aria-label="Seed set">
          {SETS.map((s) => (
            <button key={s.key} type="button" aria-pressed={set === s.key} onClick={() => setSet(s.key)}>
              {s.label}
            </button>
          ))}
        </div>
      </header>
      <AnimatePresence mode="wait">
        <m.main
          key={`${set}-${state.status}`}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: motion.quick }}
        >
          {state.status === "loading" && <Skeleton />}
          {state.status === "error" && <ErrorState message={state.message} onRetry={retry} />}
          {state.status === "missing" && <MissingState set={set} onSwitch={set === "heldout" ? () => setSet("dev") : undefined} />}
          {state.status === "ready" && <Results report={state.report} />}
        </m.main>
      </AnimatePresence>
    </div>
  );
}

function Results({ report }: { report: Report }) {
  const d = report.designs;
  const p = d.platform;
  if (!p || Object.keys(d).length === 0) {
    return <MissingState set={report.set} />;
  }
  const f = report.facts;
  return (
    <>
      <p className={`${styles.facts} num`}>
        {num(f.decisions)} decisions · {num(f.events)} card transactions, {num(f.redelivered)} delivered twice and {num(f.late_over_1m)} over a minute
        late · seeds {report.seeds.join(", ")} · config {report.config_sha}
      </p>
      <section className={styles.section}>
        <BudgetTracks designs={d} />
        {d.direct && (
          <p className={styles.note}>
            The platform spends {pct(p.spend_cut_vs_direct[0], 0)} less than querying every source (95% interval {pct(p.spend_cut_vs_direct[1], 0)}–
            {pct(p.spend_cut_vs_direct[2], 0)}), with {num(p.violations)} rule breaks and every stream feature exact.
          </p>
        )}
      </section>
      <section className={styles.section}>
        <h2 className={styles.h2}>Every design, the same decisions</h2>
        <p className={styles.note}>Intervals are 95%, resampling whole days. Referred means a feature was missing or late and the decision went to a person.</p>
        <DesignTable designs={d} />
      </section>
      <section className={styles.section}>
        <h2 className={styles.h2}>Where the platform's provider features came from</h2>
        <SourceBar sources={p.sources} />
        <ProviderTable rows={p.by_provider} />
      </section>
      <section className={styles.section}>
        <h2 className={styles.h2}>Stream features against what was knowable at the decision</h2>
        <p className={styles.note}>
          The consumer files each transaction under the minute it happened and claims its id once, so {num(p.stream_consumer.duplicates)} redeliveries
          never counted twice.
        </p>
        <StreamTable designs={d} skew={report.backfill_skew} />
      </section>
      <footer className={styles.footer}>
        Generated from <code>reports/{report.set}.json</code> at {report.generated_at}. Everything is simulated; see the README's limits.
      </footer>
    </>
  );
}
