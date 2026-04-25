import type { SourceRecord } from "../types";

export function RecordCard({ record }: { record: SourceRecord }) {
  const entries = Object.entries(record.attributes);
  const date = record.timestamp.slice(0, 10);
  return (
    <div className="card fact">
      <div className="row" style={{ justifyContent: "space-between", marginBottom: 6 }}>
        <span className="value" style={{ fontSize: 13 }}>{record.attributes.name ?? record.id}</span>
        <span className="label">{record.sourceLabel}</span>
      </div>
      {entries.filter(([k]) => k !== "name").map(([k, v]) => (
        <div className="attr-row" key={k}>
          <span className="k">{k.replace(/_/g, " ")}</span>
          <span className="v">{v}</span>
        </div>
      ))}
      <div className="source">id: {record.id} · {date}</div>
    </div>
  );
}
