"""Bireysel görünüm için 10 üzerinden genel skor.

ETİK ÇERÇEVE: Bu skor bir PERFORMANS NOTU DEĞİLDİR; kişinin kendi delivery
akışının özetidir. Kişiler arası kıyas için kullanılmaz (API'de kişi-kişi
kıyas endpoint'i yoktur), sıralama üretilmez. Amaç: "akış nerede tıkanıyor,
nasıl yardımcı olabilirim" sorusuna tek bakışta cevap.

Yöntem:
- Her metrik, config'teki green/red eşiklerine göre 0..10 arası doğrusal
  interpolasyonla puanlanır (green eşiği = 10, red eşiği = 0, arası doğrusal).
- 'insufficient_data' olan metrik skora GİRMEZ (uydurma yok) — bunun yerine
  kaç metriğin skora girdiği `covered`/`total` olarak dönülür.
- Ağırlıklandırma metriğin veri tamlığıyla yapılır: zayıf veriye dayalı metrik
  skoru daha az etkiler.
- Hiç metrik puanlanamıyorsa skor None döner ("veri yetersiz").
"""
from __future__ import annotations

from app.core.config import Config
from app.core.i18n import tr_text
from app.services.health import METRIC_THRESHOLD_MAP

# Metriğin genel skordaki temel ağırlığı (veri tamlığıyla çarpılır).
BASE_WEIGHTS: dict[str, float] = {
    "cycle_time": 1.2,
    "pr_review_time": 1.0,
    "review_latency": 1.0,
    "deployment_frequency": 1.0,
    "change_failure_rate": 1.2,
    "mttr": 1.0,
    "wip": 0.8,
    "rework": 0.8,
    "estimate_accuracy": 0.6,
    "process_hygiene": 0.6,
}

SCORE_LABELS = (
    (8.5, "Akışta"),
    (7.0, "İyi durumda"),
    (5.0, "İzlenmeli"),
    (0.0, "Zorlanıyor — yardım gerekebilir"),
)


def _lerp_score(value: float, green: float, red: float, direction: str) -> float:
    """green eşiği 10, red eşiği 0; arası doğrusal, dışı kırpılır."""
    if green == red:
        return 10.0 if (value <= green if direction == "lower" else value >= green) else 0.0
    if direction == "lower":
        raw = (red - value) / (red - green)
    else:
        raw = (value - red) / (green - red)
    return max(0.0, min(10.0, raw * 10.0))


def metric_score(metric_key: str, value: float | None, status: str, cfg: Config) -> float | None:
    """Tek metriğin 0..10 skoru. Veri yetersizse None (skora girmez)."""
    if value is None or status == "insufficient_data":
        return None
    if metric_key == "estimate_accuracy":
        # 1.0 ideal; sapma büyüdükçe düşer. |log oranı| yerine basit oransal sapma.
        if value <= 0:
            return None
        dev = abs(value - 1.0) / (1.0 if value >= 1.0 else value)
        return max(0.0, min(10.0, 10.0 - dev * 6.0))
    mapping = METRIC_THRESHOLD_MAP.get(metric_key)
    if mapping is None:
        return None
    field, direction = mapping
    th = getattr(cfg.health_thresholds, field)
    return round(_lerp_score(float(value), float(th.green), float(th.red), direction), 2)


def score_label(score: float) -> str:
    """Etiket isteğin diline göre döner (tr_text → ContextVar). Ham TR metin
    döndürülseydi İngilizce panoda skorun yanında Türkçe bir etiket kalırdı."""
    for cutoff, label in SCORE_LABELS:
        if score >= cutoff:
            return tr_text(label)
    return tr_text(SCORE_LABELS[-1][1])


def overall_score(metrics: list[dict], cfg: Config) -> dict:
    """metrics: developer_summary'nin ürettiği metrik listesi.

    Döner: {score, label, covered, total, breakdown:[{key,name,score,weight}]}
    score None ise ekranda 'veri yetersiz' gösterilir.
    """
    breakdown: list[dict] = []
    total_w = 0.0
    acc = 0.0
    for m in metrics:
        s = metric_score(m["key"], m.get("value"), m.get("status", ""), cfg)
        if s is None:
            breakdown.append({"key": m["key"], "name": m.get("name", m["key"]), "score": None, "weight": 0.0})
            continue
        completeness = m.get("data_completeness") or 0.0
        w = BASE_WEIGHTS.get(m["key"], 0.8) * max(0.0, min(1.0, float(completeness)))
        if w <= 0:
            breakdown.append({"key": m["key"], "name": m.get("name", m["key"]), "score": s, "weight": 0.0})
            continue
        acc += s * w
        total_w += w
        breakdown.append({"key": m["key"], "name": m.get("name", m["key"]), "score": s, "weight": round(w, 3)})

    covered = sum(1 for b in breakdown if b["weight"] > 0)
    if total_w <= 0:
        return {
            "score": None,
            "label": tr_text("Veri yetersiz"),
            "covered": 0,
            "total": len(metrics),
            "breakdown": breakdown,
            "note": tr_text("Skor üretmek için yeterli veri yok — eksik veri uydurulmaz."),
        }
    score = round(acc / total_w, 1)
    return {
        "score": score,
        "label": score_label(score),
        "covered": covered,
        "total": len(metrics),
        "breakdown": breakdown,
        "note": tr_text("Bu skor bir performans notu değil, kendi akışınızın özetidir; "
                        "kişiler arası kıyasta kullanılmaz."),
    }
