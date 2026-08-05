"""Sunucu tarafı dil desteği (TR / EN).

NEDEN SUNUCUDA DA GEREKLİ: metrik adları, açıklamaları ve durum etiketleri
API'den geliyor. Arayüzü tek başına çevirmek panoyu yarı Türkçe bırakırdı —
"Cycle Time · Zorlanıyor — yardım gerekebilir" gibi.

KAPSAM SINIRI (bilinçli): burada ÇEVRİLEN şey sabit sözlüktür — metrik adları,
açıklamalar, durum etiketleri, boyut adları. Kural motorunun ürettiği uzun
öneri metinleri, senkron uyarıları ve AI çıktısı hâlâ Türkçedir; onlar üretilmiş
düzyazıdır ve ayrı bir iş kalemidir. Yarım çevrilmiş bir cümle, çevrilmemiş
cümleden kötüdür.

Dil AKIŞI: arayüz `Accept-Language` başlığı gönderir → `lang_from_request`
onu okur → sözlükler o dilde döner. Tanımsız/desteklenmeyen dil TR'ye düşer.
"""
from __future__ import annotations

from fastapi import Request

DEFAULT_LANG = "tr"
SUPPORTED = ("tr", "en")


def normalize_lang(value: str | None) -> str:
    """'en-US,en;q=0.9' → 'en'. Desteklenmiyorsa varsayılana düşer."""
    if not value:
        return DEFAULT_LANG
    for parca in value.split(","):
        kod = parca.split(";")[0].strip().lower()
        kok = kod.split("-")[0]
        if kok in SUPPORTED:
            return kok
    return DEFAULT_LANG


def lang_from_request(request: Request) -> str:
    """FastAPI bağımlılığı: isteğin dilini verir."""
    return normalize_lang(request.headers.get("accept-language"))


# --- metrik adları ve açıklamaları -------------------------------------------
# (ad, açıklama) — dashboard kartlarında görünür.

METRIC_META_TR: dict[str, tuple[str, str]] = {
    "cycle_time": ("Cycle Time", "İş açıldıktan bitene kadar geçen ortalama süre (gün)"),
    "pr_review_time": ("PR Süresi", "PR açılıştan merge'e ortalama süre (gün)"),
    "review_latency": ("Review Gecikmesi", "PR açılıştan ilk review'a ortalama süre (gün)"),
    "deployment_frequency": ("Teslim Sıklığı", "Haftalık teslim (merge) sayısı"),
    "change_failure_rate": ("Geri Dönüş Oranı", "Deploy sonrası kısa sürede düzeltme gerektirme oranı"),
    "mttr": ("Toparlanma Süresi (MTTR)",
             "Incident başladıktan normale dönene kadar geçen süre (saat). Kaynak: Jira "
             "'incident' iş tipi ya da git revert; incident kaydı yoksa 'veri yetersiz'"),
    "wip": ("Açık İş (WIP)", "Kişi başına aynı anda açık iş sayısı"),
    "rework": ("Rework Oranı", "Aynı dosyaya kısa aralıkla tekrar dokunma oranı (takım)"),
    "estimate_accuracy": ("Tahmin Tutarlılığı", "Gerçekleşen / tahmin edilen süre oranı (1.0 ideal)"),
    "process_hygiene": ("Süreç Hijyeni",
                        "Sürecin veriyle izlenebilirlik oranı (estimate, status, review dolulukları)"),
}

METRIC_META_EN: dict[str, tuple[str, str]] = {
    "cycle_time": ("Cycle Time", "Average time from work opened to done (days)"),
    "pr_review_time": ("PR Time", "Average time from PR opened to merged (days)"),
    "review_latency": ("Review Latency", "Average time from PR opened to first review (days)"),
    "deployment_frequency": ("Delivery Frequency", "Deliveries (merges) per week"),
    "change_failure_rate": ("Change Failure Rate", "Share of deploys needing a quick fix afterwards"),
    "mttr": ("Time to Restore (MTTR)",
             "Time from incident start to recovery (hours). Source: Jira 'incident' issue "
             "type or git revert; without incident records this stays 'not enough data'"),
    "wip": ("Work in Progress (WIP)", "Open items per person at the same time"),
    "rework": ("Rework Rate", "Share of file touches repeated within a short window (team)"),
    "estimate_accuracy": ("Estimate Accuracy", "Actual / estimated duration ratio (1.0 is ideal)"),
    "process_hygiene": ("Process Hygiene",
                        "How traceable the process is in data (estimate, status, review coverage)"),
}

# --- durum etiketleri ---------------------------------------------------------
# DİL SEÇİMİ ÖNEMLİ: kırmızı bir ceza değil, destek çağrısıdır. İngilizce
# karşılık da bu çerçeveyi korur ("struggling — support may help"), "bad"/"fail"
# gibi bir performans dili KULLANILMAZ.

STATUS_LABELS_TR = {
    "green": "Akıyor",
    "yellow": "İzlenmeli",
    "red": "Zorlanıyor — yardım gerekebilir",
    "insufficient_data": "Veri yetersiz",
}

STATUS_LABELS_EN = {
    "green": "Flowing",
    "yellow": "Worth watching",
    "red": "Struggling — support may help",
    "insufficient_data": "Not enough data",
}

# --- kod analizi boyutları ----------------------------------------------------

DIM_LABELS_TR = {
    "readability": "Okunabilirlik",
    "complexity": "Karmaşıklık",
    "maintainability": "Bakım kolaylığı",
    "test_adequacy": "Test yeterliliği",
    "security": "Güvenlik",
    "code_smells": "Kod kokuları / temizlik",
    "conventions": "Konvansiyonlar",
}

DIM_LABELS_EN = {
    "readability": "Readability",
    "complexity": "Complexity",
    "maintainability": "Maintainability",
    "test_adequacy": "Test adequacy",
    "security": "Security",
    "code_smells": "Code smells / cleanliness",
    "conventions": "Conventions",
}


def metric_meta(lang: str = DEFAULT_LANG) -> dict[str, tuple[str, str]]:
    return METRIC_META_EN if lang == "en" else METRIC_META_TR


def status_labels(lang: str = DEFAULT_LANG) -> dict[str, str]:
    return STATUS_LABELS_EN if lang == "en" else STATUS_LABELS_TR


def dim_labels(lang: str = DEFAULT_LANG) -> dict[str, str]:
    return DIM_LABELS_EN if lang == "en" else DIM_LABELS_TR
