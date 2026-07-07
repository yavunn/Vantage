// Haftalık trend — tek seri çizgi (legend gerekmez, başlık seriyi adlandırır).
// Veri olmayan kovalar boşluk olarak görünür (connectNulls yok): eksik veri
// dürüstçe boşluktur, sıfır değildir.
import {
  CartesianGrid,
  Line,
  LineChart,
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

export default function TrendChart({ series }) {
  const data = series.points.map((p) => ({
    label: fmtDate(p.period_start),
    value: p.value,
    completeness: p.data_completeness,
  }));
  const hasAny = data.some((d) => d.value != null);
  return (
    <div className="chart-box">
      <h3>{series.name}</h3>
      <p className="desc">{series.description}</p>
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
