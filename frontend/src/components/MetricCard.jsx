// Sağlık göstergesi kartı. Renk = durum (destek dili), asla kişi puanı değil.
// "Veri yetersiz" birinci sınıf bir durumdur: değer uydurulmaz, gri gösterilir.
const STATUS_COLOR = {
  green: "var(--status-good)",
  yellow: "var(--status-warning)",
  red: "var(--status-critical)",
  insufficient_data: "var(--status-neutral)",
};

const STATUS_ICON = { green: "✓", yellow: "▲", red: "●", insufficient_data: "–" };

const UNITS = {
  cycle_time: "gün",
  pr_review_time: "gün",
  review_latency: "gün",
  deployment_frequency: "/hafta",
  wip: "iş/kişi",
};

const PERCENT_METRICS = new Set(["change_failure_rate", "rework", "process_hygiene"]);

export function formatValue(key, value) {
  if (value == null) return null;
  if (PERCENT_METRICS.has(key)) return `%${(value * 100).toFixed(0)}`;
  if (key === "estimate_accuracy") return `${value.toFixed(2)}×`;
  return value.toFixed(1);
}

export default function MetricCard({ metric, previous }) {
  const insufficient = metric.status === "insufficient_data";
  const color = STATUS_COLOR[metric.status];
  const completenessPct = Math.round(metric.data_completeness * 100);
  return (
    <div className={`card${insufficient ? " insufficient" : ""}`}>
      <div className="metric-head">
        <span className="dot" style={{ background: color }} aria-hidden="true" />
        <h3>{metric.name}</h3>
      </div>
      <div className="value">
        {insufficient ? (
          "Veri yetersiz"
        ) : (
          <>
            {formatValue(metric.key, metric.value)}
            {UNITS[metric.key] && <span className="unit">{UNITS[metric.key]}</span>}
          </>
        )}
      </div>
      {previous != null && metric.value != null && (
        <div className="prev">
          Kendi geçmişiniz (önceki dönem): {formatValue(metric.key, previous)}
        </div>
      )}
      <p className="desc">{metric.description}</p>
      <div className="meta">
        <span className="status-label" style={{ color }}>
          {STATUS_ICON[metric.status]} {metric.status_label}
        </span>
        <span title="Bu metriğin dayandığı kayıtların ne kadarında gerekli alanlar vardı">
          veri tamlığı %{completenessPct}
          {metric.source_layer ? ` · ${metric.source_layer}` : ""}
        </span>
      </div>
    </div>
  );
}
