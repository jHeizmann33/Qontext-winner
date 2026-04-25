import { useMemo } from "react";
import { sampleRecords } from "./data/sampleRecords";
import { resolve } from "./resolver";
import { RecordCard } from "./components/RecordCard";
import { ClusterCard } from "./components/ClusterCard";

export function App() {
  const result = useMemo(() => resolve(sampleRecords), []);

  return (
    <div className="app">
      <header className="app-header">
        <h1>Qontext — Resolver Demo</h1>
        <p className="sub">
          Records flow in from multiple sources. The resolver dedups, auto-merges, and flags ambiguous matches for human review.
        </p>
      </header>

      <div className="columns">
        <section className="column">
          <div className="column-header">
            <span className="title">Incoming records</span>
            <span className="count">{sampleRecords.length} from {new Set(sampleRecords.map((r) => r.source)).size} sources</span>
          </div>
          <div className="column-body">
            {sampleRecords.map((r) => <RecordCard key={r.id} record={r} />)}
          </div>
        </section>

        <section className="column">
          <div className="column-header">
            <span className="title">Auto-resolved entities</span>
            <span className="count">{result.autoResolved.length} merged · {result.singletons.length} singletons</span>
          </div>
          <div className="column-body">
            {result.autoResolved.length === 0 && result.singletons.length === 0 && (
              <div className="empty">No clusters yet</div>
            )}
            {result.autoResolved.map((c) => <ClusterCard key={c.id} cluster={c} />)}
            {result.singletons.map((c) => <ClusterCard key={c.id} cluster={c} />)}
          </div>
        </section>

        <section className="column">
          <div className="column-header">
            <span className="title">Review inbox</span>
            <span className="count">{result.needsReview.length} pending</span>
          </div>
          <div className="column-body">
            {result.needsReview.length === 0 ? (
              <div className="empty">No ambiguous clusters</div>
            ) : (
              result.needsReview.map((c) => <ClusterCard key={c.id} cluster={c} />)
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
