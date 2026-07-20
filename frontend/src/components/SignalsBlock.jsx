// Sağlık / tükenmişlik sinyalleri. DORA metrikleri değil; "takım zorlanıyor mu"
// sorusuna yumuşak yanıt. Kırmızı = yardım gerekebilir. Kişi ismi YOK — yalnızca
// dağılım/oran. Veri yoksa dürüstçe "veri yetersiz".
const STATUS_COLOR = {
  green: "var(--status-good)",
  yellow: "var(--status-warning)",
  red: "var(--status-critical)",
  insufficient_data: "var(--status-neutral)",
};
const STATUS_ICON = { green: "✓", yellow: "▲", red: "●", insufficient_data: "–" };

function fmtSignal(sig) {
  if (sig.value == null) return "Veri yetersiz";
  // leave_usage / off_hours / concentration / review_load hepsi oran → yüzde
  return `%${Math.round(sig.value * 100)}`;
}

export default function SignalsBlock({ signals }) {
  if (!signals || signals.length === 0) return null;
  return (
    <section className="section">
      <h2>Sağlık sinyalleri</h2>
      <p className="desc" style={{ marginTop: -6, marginBottom: 12 }}>
        Süreç metriği değil, takım sağlığına dair yumuşak sinyaller. Kırmızı
        "zorlanıyor, yardım gerekebilir" demektir; kişi ismi gösterilmez.
      </p>
      <div className="cards">
        {signals.map((sig) => {
          const insufficient = sig.status === "insufficient_data";
          const color = STATUS_COLOR[sig.status];
          return (
            <div key={sig.key} className={`card${insufficient ? " insufficient" : ""}`}>
              <div className="metric-head">
                <span className="dot" style={{ background: color }} aria-hidden="true" />
                <h3>{sig.name}</h3>
              </div>
              <div className="value">
                {insufficient ? "Veri yetersiz" : fmtSignal(sig)}
              </div>
              <p className="desc">{sig.description}</p>
              <div className="meta">
                <span className="status-label" style={{ color }}>
                  {STATUS_ICON[sig.status]} {sig.status_label}
                </span>
                {sig.sample_size != null && !insufficient && (
                  <span>
                    {sig.reviewer_count != null
                      ? `${sig.reviewer_count} kişi · ${sig.sample_size} review`
                      : `${sig.sample_size} kayıt`}
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
