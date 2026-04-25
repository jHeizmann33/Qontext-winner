import type { Cluster } from "../types";

function confidenceBadge(score: number) {
  if (score >= 0.85) return <span className="confidence high">{(score * 100).toFixed(0)}% match</span>;
  if (score >= 0.6) return <span className="confidence med">{(score * 100).toFixed(0)}% match</span>;
  return <span className="confidence low">{(score * 100).toFixed(0)}% match</span>;
}

export function ClusterCard({ cluster }: { cluster: Cluster }) {
  const cls = cluster.status === "auto-resolved" ? "card resolved" : cluster.status === "needs-review" ? "card review" : "card";
  const headline =
    cluster.attributes.name?.picked?.value ??
    cluster.attributes.email?.picked?.value ??
    cluster.records[0]?.id ??
    "(unnamed)";

  return (
    <div className={cls}>
      <div className="row" style={{ justifyContent: "space-between", marginBottom: 6 }}>
        <span className="value" style={{ fontSize: 14 }}>{headline}</span>
        {cluster.records.length > 1 && confidenceBadge(cluster.matchScore)}
      </div>

      <div style={{ marginBottom: 6 }}>
        {Object.entries(cluster.attributes)
          .filter(([k]) => k !== "name")
          .map(([key, attr]) => (
            <div className="attr-row" key={key}>
              <span className="k">{key.replace(/_/g, " ")}</span>
              <span className="v">
                {attr.conflict ? (
                  <div className="conflict">
                    {attr.values.map((v, i) => (
                      <div className="conflict-option" key={i}>
                        <span>{v.value}</span>
                        <span className="src">{v.sourceLabel}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <span>
                    {attr.picked?.value}
                    <span className="src" style={{ marginLeft: 6, color: "var(--muted)", fontSize: 11 }}>
                      ({attr.picked?.sourceLabel})
                    </span>
                  </span>
                )}
              </span>
            </div>
          ))}
      </div>

      {cluster.records.length > 1 && (
        <div className="source" style={{ marginTop: 6 }}>
          <strong style={{ color: "var(--muted)" }}>Merged from:</strong>{" "}
          {cluster.records.map((r) => r.id).join(", ")}
        </div>
      )}

      {cluster.matchReasons.length > 0 && (
        <div className="source" style={{ marginTop: 4 }}>
          <strong style={{ color: "var(--muted)" }}>Match reasons:</strong>
          <ul style={{ margin: "2px 0 0", paddingLeft: 16 }}>
            {cluster.matchReasons.map((r, i) => (
              <li key={i} style={{ fontSize: 11 }}>{r}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
