// Haftalık trend — tek seri çizgi (legend gerekmez, başlık seriyi adlandırır).
// Veri olmayan kovalar boşluk olarak görünür (connectNulls yok): eksik veri
// dürüstçe boşluktur, sıfır değildir.
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { formatValue } from "./MetricCard.jsx";

function fmtDate(s) {
  const d = new Date(s);
  return `${d.getDate()}.${d.getMonth() + 1}`;
}

// Anotasyon tarihini, içine düştüğü kovaya eşle → o kovanın etiketinde işaret.
function annotationsForBuckets(points, annotations) {
  if (!annotations || annotations.length === 0) return [];
  const out = [];
  for (const a of annotations) {
    const ad = a.date; // YYYY-MM-DD
    const bucket = points.find((p) => ad >= p.period_start && ad <= p.period_end);
    if (bucket) out.push({ bucketLabel: fmtDate(bucket.period_start), text: a.label, kind: a.kind });
  }
  return out;
}

const KIND_COLOR = {
  holiday: "var(--status-good)",
  incident: "var(--status-critical)",
  release: "var(--series-1)",
  other: "var(--muted)",
};

// Otomatik trend özeti: grafiği okumadan "ne oldu" cümlesi. Karar hızlandırır.
// Kıyas SADECE serinin kendi geçmişiyle — başka takım/kişiyle asla.
function trendSummary(series) {
  const vals = series.points.map((p) => p.value).filter((v) => v != null);
  if (vals.length < 3) return null;
  // İlk yarı vs son yarı ortalaması: tek kovanın gürültüsüne kapılmaz.
  const half = Math.floor(vals.length / 2);
  const avg = (xs) => xs.reduce((a, b) => a + b, 0) / xs.length;
  const first = avg(vals.slice(0, half));
  const last = avg(vals.slice(-half));
  if (first === 0) return null;
  const pct = ((last - first) / Math.abs(first)) * 100;
  const rounded = Math.round(Math.abs(pct));
  const periods = vals.length;
  if (rounded < 5) return { tone: "flat", text: `Son ${periods} dönemde belirgin değişim yok — seyir sabit.` };
  const up = pct > 0;
  const direction = series.direction || "lower";
  const good = direction === "higher" ? up : !up;
  return {
    tone: good ? "good" : "bad",
    text: good
      ? `Son ${periods} dönemde %${rounded} iyileşme — gidişat olumlu.`
      : `Son ${periods} dönemde %${rounded} kötüleşme — yakından izlemekte fayda var.`,
  };
}

export default function TrendChart({ series, threshold, annotations }) {
  const data = series.points.map((p) => ({
    label: fmtDate(p.period_start),
    value: p.value,
    completeness: p.data_completeness,
  }));
  const marks = annotationsForBuckets(series.points, annotations);
  const hasAny = data.some((d) => d.value != null);
  const summary = hasAny ? trendSummary(series) : null;
  return (
    <div className="chart-box">
      <h3>{series.name}</h3>
      <p className="desc">{series.description}</p>
      {summary && <p className={`trend-summary ${summary.tone}`}>{summary.text}</p>}
      {!hasAny ? (
        <p className="desc" style={{ padding: "30px 0", textAlign: "center" }}>
          Bu dönem için yeterli veri yok
        </p>
      ) : (
        <ResponsiveContainer width="100%" height={180}>
          <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -18 }}>
            <CartesianGrid stroke="var(--grid)" vertical={false} />
            <XAxis
              dataKey="label"
              tick={{ fill: "var(--muted)", fontSize: 11 }}
              axisLine={{ stroke: "var(--grid)" }}
              tickLine={false}
            />
            <YAxis
              tick={{ fill: "var(--muted)", fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              width={58}
            />
            <Tooltip
              contentStyle={{
                background: "var(--surface-1)",
                border: "1px solid var(--border)",
                borderRadius: 8,
                color: "var(--text-primary)",
                fontSize: 12.5,
              }}
              formatter={(v) => [formatValue(series.metric, v), series.name]}
            />
            {/* Hedef/eşik çizgileri: yeşil = sağlıklı sınır, kırmızı = zorlanma */}
            {threshold && (
              <ReferenceLine
                y={threshold.green}
                stroke="var(--status-good)"
                strokeDasharray="4 4"
                strokeOpacity={0.7}
                label={{ value: `hedef ${threshold.green}`, position: "insideTopRight", fill: "var(--muted)", fontSize: 10 }}
              />
            )}
            {threshold && (
              <ReferenceLine
                y={threshold.red}
                stroke="var(--status-critical)"
                strokeDasharray="4 4"
                strokeOpacity={0.6}
                label={{ value: `eşik ${threshold.red}`, position: "insideBottomRight", fill: "var(--muted)", fontSize: 10 }}
              />
            )}
            {/* Anotasyonlar: tatil/incident/sürüm — tepe/çukur yanlış okunmasın */}
            {marks.map((m, i) => (
              <ReferenceLine
                key={`ann-${i}`}
                x={m.bucketLabel}
                stroke={KIND_COLOR[m.kind] || KIND_COLOR.other}
                strokeWidth={1.5}
                label={{ value: `⚑ ${m.text}`, position: "top", fill: KIND_COLOR[m.kind] || KIND_COLOR.other, fontSize: 10 }}
              />
            ))}
            <Line
              type="monotone"
              dataKey="value"
              stroke="var(--series-1)"
              strokeWidth={2}
              dot={{ r: 3, fill: "var(--series-1)", strokeWidth: 0 }}
              activeDot={{ r: 5 }}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
