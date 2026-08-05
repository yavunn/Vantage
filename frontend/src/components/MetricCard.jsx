import { useState } from "react";
import Sparkline from "./Sparkline.jsx";
import { useT } from "../i18n.jsx";

// İK-dostu sade açıklamalar: metrik ne ölçer, iyi/kötü ne demek. Teknik
// olmayan kullanıcı "?" ile görür. (Ölçümü değiştirmez, yalnızca anlatır.)
const METRIC_INFO = {
  cycle_time: {
    means: "Bir işin açılmasından bitmesine kadar geçen ortalama süre.",
    good: "Kısa = iş akıcı ilerliyor.",
    watch: "Uzarsa: iş tıkanıyor, bağımlılık ya da belirsizlik olabilir.",
  },
  pr_review_time: {
    means: "Bir kod değişikliğinin (PR) açılıp birleştirilmesine kadar geçen süre.",
    good: "Kısa = değişiklikler hızlı entegre oluyor.",
    watch: "Uzarsa: gözden geçirme darboğazı olabilir.",
  },
  review_latency: {
    means: "PR açıldıktan ilk geri bildirime kadar geçen süre.",
    good: "Kısa = ekip birbirine hızlı dönüyor.",
    watch: "Uzarsa: kimse bakmıyor olabilir; iş bekliyor.",
  },
  deployment_frequency: {
    means: "Haftada kaç kez teslim/yayın yapıldığı.",
    good: "Yüksek = küçük, sık, güvenli teslimler.",
    watch: "Düşükse: büyük riskli teslimler ya da tıkanma.",
  },
  change_failure_rate: {
    means: "Teslimlerden sonra kısa sürede düzeltme gerektirenlerin oranı.",
    good: "Düşük = teslimler sağlam.",
    watch: "Yüksekse: kalite/test süreci güçlendirilmeli. (Takım göstergesi, kişi değil.)",
  },
  mttr: {
    means: "Bir arıza sonrası normale dönme süresi.",
    good: "Kısa = sorunlardan hızlı toparlanılıyor.",
    watch: "Uzarsa: müdahale/izleme süreci iyileştirilmeli.",
  },
  wip: {
    means: "Kişi başına aynı anda açık iş sayısı.",
    good: "Az = odak var, işler bitiyor.",
    watch: "Çok = herkes çok işe bölünmüş, hiçbiri bitmiyor olabilir.",
  },
  rework: {
    means: "Aynı dosyaya kısa sürede tekrar dokunma oranı (takım).",
    good: "Düşük = işler ilk seferde oturuyor.",
    watch: "Yüksekse: belirsiz gereksinim ya da kırılgan kod bölgesi.",
  },
  process_hygiene: {
    means: "Sürecin veriyle ne kadar izlenebilir olduğu (tahmin/durum/review dolulukları).",
    good: "Yüksek = süreç şeffaf, planlama sağlıklı.",
    watch: "Düşükse: süreç körlüğü var; kararlar veriye dayanmıyor.",
  },
};

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
function fmtStat(t, key, v) {
  if (v == null) return "–";
  if (key === "mttr") return `${v.toFixed(0)} ${t("saat")}`;
  return `${v.toFixed(1)} ${t("gün")}`;
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
  const t = useT();
  if (previous == null || metric.value == null || previous === 0) return null;
  const pct = ((metric.value - previous) / Math.abs(previous)) * 100;
  if (!isFinite(pct)) return null;
  const rounded = Math.round(pct);
  if (rounded === 0) return <span className="delta flat">{t("≈ değişim yok")}</span>;
  const up = pct > 0;
  const direction = metric.direction || "lower";
  // Yükselmesi iyi mi? higher metrikte artış iyi; lower metrikte azalış iyi.
  const good = direction === "higher" ? up : !up;
  return (
    <span className={`delta ${good ? "good" : "bad"}`} title={t("Önceki eş döneme göre")}>
      {up ? "↑" : "↓"} %{Math.abs(rounded)}
    </span>
  );
}

export default function MetricCard({ metric, previous, onClick, series }) {
  const t = useT();
  const insufficient = metric.status === "insufficient_data";
  const color = STATUS_COLOR[metric.status];
  const completenessPct = Math.round(metric.data_completeness * 100);
  const clickable = typeof onClick === "function";
  const [info, setInfo] = useState(false);
  const meta = METRIC_INFO[metric.key];
  return (
    <div
      className={`card${insufficient ? " insufficient" : ""}${clickable ? " clickable" : ""}`}
      // Durum, kartın üst aksan şeridini boyar (CSS). Nokta + metin etiketiyle
      // birlikte üçüncü kanal; renk tek başına anlam taşımaz.
      data-status={metric.status}
      onClick={onClick}
      role={clickable ? "button" : undefined}
      tabIndex={clickable ? 0 : undefined}
      onKeyDown={clickable ? (e) => { if (e.key === "Enter") onClick(); } : undefined}
      title={clickable ? t("Detay için tıkla (hangi kayıtlar bu sayıyı oluşturuyor)") : undefined}
    >
      <div className="metric-head">
        <span className="dot" style={{ background: color }} aria-hidden="true" />
        <h3>{metric.name}</h3>
        {meta && (
          <button
            className="info-btn"
            aria-label={t("Bu metrik ne anlama geliyor?")}
            aria-expanded={info}
            onClick={(e) => { e.stopPropagation(); setInfo((v) => !v); }}
          >?</button>
        )}
        {metric.direction && <Delta metric={metric} previous={previous} />}
      </div>
      {info && meta && (
        <div className="metric-info" onClick={(e) => e.stopPropagation()}>
          <p><strong>{t("Ne ölçer:")}</strong> {t(meta.means)}</p>
          <p className="mi-good"><strong>{t("İyi:")}</strong> {t(meta.good)}</p>
          <p className="mi-watch"><strong>{t("Dikkat:")}</strong> {t(meta.watch)}</p>
        </div>
      )}
      <div className="value">
        {insufficient ? (
          t("Veri yetersiz")
        ) : (
          <>
            {formatValue(metric.key, metric.value)}
            {UNITS[metric.key] && <span className="unit">{t(UNITS[metric.key])}</span>}
          </>
        )}
      </div>
      {!insufficient && series && series.points && (
        <div className="card-spark" title={t("Son dönemlerin seyri (ayrıntı için alttaki trend grafiği)")}>
          <Sparkline points={series.points} color={color} />
        </div>
      )}
      {!metric.direction && previous != null && metric.value != null && (
        <div className="prev">
          {t("Kendi geçmişiniz (önceki dönem):")} {formatValue(metric.key, previous)}
        </div>
      )}
      {!insufficient && metric.stats && (
        // Ortalama tek başına yanıltıcı: medyan + p90 yanına eklenir (İlke:
        // istatistiksel dürüstlük). Ortalama üstteki büyük değerdir.
        <div className="dist" title={t("Ortalama yanıltıcı olabilir; medyan ve p90 dağılımı gösterilir")}>
          <span>{t("medyan")} {fmtStat(t, metric.key, metric.stats.median)}</span>
          <span>p90 {fmtStat(t, metric.key, metric.stats.p90)}</span>
        </div>
      )}
      <p className="desc">{metric.description}</p>
      <div className="meta">
        <span className="status-label" style={{ color }}>
          {STATUS_ICON[metric.status]} {metric.status_label}
        </span>
        <span title={t("Bu metriğin dayandığı kayıtların ne kadarında gerekli alanlar vardı")}>
          {t("veri tamlığı %{pct}", { pct: completenessPct })}
          {metric.source_layer ? ` · ${metric.source_layer}` : ""}
        </span>
      </div>
      {!insufficient && metric.sample_size != null && (
        <div className={`sample${metric.sample_size < LOW_SAMPLE ? " low" : ""}`}>
          {metric.sample_size < LOW_SAMPLE
            ? t("⚠ yalnızca {n} kayıt — az örneklem, dikkatli yorumla", { n: metric.sample_size })
            : t("{n} kayıt üzerinden", { n: metric.sample_size })}
        </div>
      )}
    </div>
  );
}
