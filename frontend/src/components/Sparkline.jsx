// Minik trend çizgisi (kütüphanesiz, saf SVG). Kartın içinde "son haftalarda
// ne oldu" sorusunu tek bakışta yanıtlar. Eksen/etiket yok — bilinçli: kart
// içinde ayrıntı değil YÖN okunur; ayrıntı için büyük trend grafiği var.
export default function Sparkline({ points, color = "var(--series-1)", width = 100, height = 24 }) {
  const vals = (points || []).map((p) => p.value).filter((v) => v != null);
  if (vals.length < 2) return null;

  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const span = max - min || 1;
  const stepX = width / (vals.length - 1);
  const coords = vals.map((v, i) => {
    const x = i * stepX;
    // Üst/alt 2px pay: uç noktalar kırpılmasın.
    const y = height - 2 - ((v - min) / span) * (height - 4);
    return [x, y];
  });
  const d = coords.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const area = `${d} L${width},${height} L0,${height} Z`;
  const [lastX, lastY] = coords[coords.length - 1];

  return (
    <svg
      className="sparkline"
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      role="img"
      aria-label={`Son ${vals.length} dönem trendi`}
      preserveAspectRatio="none"
    >
      <path d={area} fill={color} opacity="0.12" />
      <path d={d} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={lastX} cy={lastY} r="2" fill={color} />
    </svg>
  );
}
