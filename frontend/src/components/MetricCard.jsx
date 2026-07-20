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
  mttr: "saat",
  wip: "iş/kişi",
};

// Az örneklemle hesaplanan metrik yanıltıcı olabilir — bu eşiğin altında uyar.
const LOW_SAMPLE = 5;

// stats dağılımı gösterilen (ortalama yanıltıcı olabilen) süre metrikleri.
// Birim gün olanlarda 1 ondalık, saat (mttr) olanda tam sayı okunur.
function fmtStat(key, v) {
  if (v == null) return "–";
  if (key === "mttr") return `${v.toFixed(0)} saat`;
  return `${v.toFixed(1)} gün`;
}

const PERCENT_METRICS = new Set(["change_failure_rate", "rework", "process_hygiene"]);

export function formatValue(key, value) {
  if (value == null) return null;
  if (PERCENT_METRICS.has(key)) return `%${(value * 100).toFixed(0)}`;
  if (key === "estimate_accuracy") return `${value.toFixed(2)}×`;
  return value.toFixed(1);
}

// Önceki döneme göre değişim oku. direction='lower' (cycle time gibi) → artış
// KÖTÜ (kırmızı), azalış iyi. direction='higher' (deploy sıklığı) → tersi.
// Renk yönü metriğe göre ayrı kurulur; ok her zaman gerçek yönü gösterir.
function Delta({ metric, previous }) {
  if (previous == null || metric.value == null || previous === 0) return null;
  const pct = ((metric.value - previous) / Math.abs(previous)) * 100;
  if (!isFinite(pct)) return null;
  const rounded = Math.round(pct);
  if (rounded === 0) return <span className="delta flat">≈ değişim yok</span>;
  const up = pct > 0;
  const direction = metric.direction || "lower";
  // Yükselmesi iyi mi? higher metrikte artış iyi; lower metrikte azalış iyi.
  const good = direction === "higher" ? up : !up;
  return (
    <span className={`delta ${good ? "good" : "bad"}`} title="Önceki eş döneme göre">
      {up ? "↑" : "↓"} %{Math.abs(rounded)}
    </span>
  );
}

export default function MetricCard({ metric, previous, onClick }) {
  const insufficient = metric.status === "insufficient_data";
  const color = STATUS_COLOR[metric.status];
  const completenessPct = Math.round(metric.data_completeness * 100);
  const clickable = typeof onClick === "function";
  return (
    <div
      className={`card${insufficient ? " insufficient" : ""}${clickable ? " clickable" : ""}`}
      onClick={onClick}
      role={clickable ? "button" : undefined}
      tabIndex={clickable ? 0 : undefined}
      onKeyDown={clickable ? (e) => { if (e.key === "Enter") onClick(); } : undefined}
      title={clickable ? "Detay için tıkla (hangi kayıtlar bu sayıyı oluşturuyor)" : undefined}
    >
      <div className="metric-head">
        <span className="dot" style={{ background: color }} aria-hidden="true" />
        <h3>{metric.name}</h3>
        {metric.direction && <Delta metric={metric} previous={previous} />}
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
      {!metric.direction && previous != null && metric.value != null && (
        <div className="prev">
          Kendi geçmişiniz (önceki dönem): {formatValue(metric.key, previous)}
        </div>
      )}
      {!insufficient && metric.stats && (
        // Ortalama tek başına yanıltıcı: medyan + p90 yanına eklenir (İlke:
        // istatistiksel dürüstlük). Ortalama üstteki büyük değerdir.
        <div className="dist" title="Ortalama yanıltıcı olabilir; medyan ve p90 dağılımı gösterilir">
          <span>medyan {fmtStat(metric.key, metric.stats.median)}</span>
          <span>p90 {fmtStat(metric.key, metric.stats.p90)}</span>
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
      {!insufficient && metric.sample_size != null && (
        <div className={`sample${metric.sample_size < LOW_SAMPLE ? " low" : ""}`}>
          {metric.sample_size < LOW_SAMPLE
            ? `⚠ yalnızca ${metric.sample_size} kayıt — az örneklem, dikkatli yorumla`
            : `${metric.sample_size} kayıt üzerinden`}
        </div>
      )}
    </div>
  );
}
