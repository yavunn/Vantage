// AI Kod Sağlığı kartı. Composite skor (repo/modül düzeyi, KİŞİ DEĞİL). Diğer
// metrik kartlarıyla aynı görsel dil. Analiz yoksa "Analiz bekliyor".
const STATUS_COLOR = {
  green: "var(--status-good)",
  yellow: "var(--status-warning)",
  red: "var(--status-critical)",
  insufficient_data: "var(--status-neutral)",
};
const STATUS_ICON = { green: "✓", yellow: "▲", red: "●", insufficient_data: "–" };

export default function CodeHealthCard({ health, onClick }) {
  if (!health) return null;
  const insufficient = health.status === "insufficient_data";
  const color = STATUS_COLOR[health.status];
  const clickable = typeof onClick === "function" && !insufficient;
  return (
    <div
      className={`card${insufficient ? " insufficient" : ""}${clickable ? " clickable" : ""}`}
      onClick={clickable ? onClick : undefined}
      role={clickable ? "button" : undefined}
      tabIndex={clickable ? 0 : undefined}
      onKeyDown={clickable ? (e) => { if (e.key === "Enter") onClick(); } : undefined}
      title={clickable ? "Detay: en çok dikkat isteyen modüller/dosyalar" : undefined}
    >
      <div className="metric-head">
        <span className="dot" style={{ background: color }} aria-hidden="true" />
        <h3>{health.name}</h3>
      </div>
      <div className="value">
        {insufficient ? "Analiz bekliyor" : health.value}
        {!insufficient && <span className="unit">/100</span>}
      </div>
      {!insufficient && health.dimension_averages && (
        <div className="dist" style={{ flexWrap: "wrap" }}>
          {Object.entries(health.dimension_averages)
            .sort((a, b) => a[1] - b[1])
            .slice(0, 3)
            .map(([label, v]) => (
              <span key={label} title="En zayıf 3 boyut (yardım isteyen alanlar)">{label} {v}</span>
            ))}
        </div>
      )}
      <p className="desc">{health.description}</p>
      <div className="meta">
        <span className="status-label" style={{ color }}>
          {STATUS_ICON[health.status]} {health.status_label}
        </span>
        {insufficient ? (
          <span>{health.note || "veri yok"}</span>
        ) : (
          <span>{health.modules?.length || 0} modül · {health.sample_size} dosya</span>
        )}
      </div>
    </div>
  );
}
