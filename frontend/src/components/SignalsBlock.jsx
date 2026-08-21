import { useT } from "../i18n.jsx";

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

export default function SignalsBlock({ signals }) {
  const t = useT();
  if (!signals || signals.length === 0) return null;
  function fmtSignal(sig) {
    if (sig.value == null) return t("Veri yetersiz");
    // leave_usage / off_hours / concentration / review_load hepsi oran → yüzde
    return `%${Math.round(sig.value * 100)}`;
  }
  return (
    <section className="section signals-section">
      <h2>{t("Sağlık sinyalleri")}</h2>
      <p className="desc" style={{ marginTop: -6, marginBottom: 12 }}>
        {t("Süreç metriği değil, takım sağlığına dair yumuşak sinyaller. Kırmızı \"zorlanıyor, yardım gerekebilir\" demektir; kişi ismi gösterilmez.")}
      </p>
      {/* signal-cards: metrik kartlarıyla aynı ızgarayı kullanır ama görsel
          olarak daha hafiftir — bunlar ölçüm değil yumuşak sinyaldir ve
          ekranda o ağırlıkta durmalıdır. */}
      <div className="cards signal-cards">
        {signals.map((sig) => {
          const insufficient = sig.status === "insufficient_data";
          const color = STATUS_COLOR[sig.status];
          return (
            // data-status: metrik kartındaki ile aynı kanca. Sol durum
            // çizgisini CSS bu değerden boyar (renk tek kanal değil — nokta ve
            // durum etiketi zaten kartın içinde).
            <div
              key={sig.key}
              className={`card${insufficient ? " insufficient" : ""}`}
              data-status={sig.status}
            >
              <div className="metric-head">
                <span className="dot" style={{ background: color }} aria-hidden="true" />
                <h3>{sig.name}</h3>
              </div>
              <div className="value">
                {insufficient ? t("Veri yetersiz") : fmtSignal(sig)}
              </div>
              <p className="desc">{sig.description}</p>
              <div className="meta">
                <span className="status-label" style={{ color }}>
                  {STATUS_ICON[sig.status]} {sig.status_label}
                </span>
                {sig.sample_size != null && !insufficient && (
                  <span>
                    {sig.reviewer_count != null
                      ? t("{n} kişi · {m} review", { n: sig.reviewer_count, m: sig.sample_size })
                      : t("{n} kayıt", { n: sig.sample_size })}
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
