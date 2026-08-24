"""Sunucu tarafı dil desteği (TR / EN).

NEDEN SUNUCUDA DA GEREKLİ: metrik adları, açıklamaları, durum etiketleri VE
hata mesajları API'den geliyor. Arayüzü tek başına çevirmek panoyu yarı
Türkçe bırakırdı — "Cycle Time · Zorlanıyor — yardım gerekebilir" gibi ya da
İngilizce arayüzde aniden Türkçe bir 422 mesajı çıkması gibi.

ÇEVRİLEN: metrik adları, açıklamalar, durum etiketleri, boyut adları,
`HTTPException` hata mesajları (`tr_error` → errors_en.py) ve API'nin içerik
olarak döndürdüğü metinler — genel skor etiketi/notu, commit-kod eşleşmesi
özeti, 1:1 hazırlık başlıkları, kural motorunun süreç önerileri
(`tr_text` → texts_en.py). Hepsi AYNI gettext kuralı: TR kaynak metin
ANAHTARDIR, eksik çeviri TR'ye düşer, ham anahtar asla dönmez.

Kural motorunun önerileri ŞABLON + PARAMETRE olarak saklanır
(`Recommendation.message` + `.params`) ve çeviri OKUMA anında yapılır; sayı
içeren cümleler de bu sayede çevrilebilir. Params'ı olmayan eski satırlar TR
metniyle gösterilir — bir sonraki senkronda yenilenirler.

KAPSAM SINIRI (bilinçli): senkron uyarıları ve LLM çıktısı (kod analizi
özetleri, asistan cevapları) çevrilmez — onlar sabit anahtar değil, çalışma
anında ÜRETİLMİŞ düzyazıdır. Yarım çevrilmiş bir cümle, çevrilmemiş cümleden
kötüdür.

Dil AKIŞI (iki yol, aynı sonuca çıkar):
  1. `lang_from_request` — bir uç `request: Request` alıyorsa doğrudan okur.
  2. `LanguageMiddleware` (app/main.py) + `tr_error` — hata mesajları YÜZLERCE
     çağrı noktasında (`raise HTTPException(...)`) üretiliyor; her birine
     `request: Request` eklemek imza kirliliği ve unutma riski demekti.
     Middleware her isteğin başında dili bir ContextVar'a yazar; `tr_error`
     onu okuyup çeviriyi orada uygular. Senkron path fonksiyonları FastAPI
     tarafından threadpool'a (anyio.to_thread) taşınır ama ContextVar,
     Python'un context-copy garantisi gereği o thread'e DE taşınır — bu
     yüzden `tr_error`'ı çağıran fonksiyonun `request` parametresi almasına
     gerek YOK.
"""
from __future__ import annotations

import contextvars

from fastapi import Request

DEFAULT_LANG = "tr"
SUPPORTED = ("tr", "en")

_current_lang: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_lang", default=DEFAULT_LANG
)


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


def set_current_lang(lang: str) -> contextvars.Token:
    """`LanguageMiddleware` her istek başında çağırır. Token, middleware'in
    isteği bitince ContextVar'ı eski değerine döndürmesi için (ASGI sunucusu
    aynı thread'i sıradaki isteklerde de kullanabilir; sıfırlanmazsa bir
    isteğin dili sonrakine SIZAR)."""
    return _current_lang.set(lang)


def reset_current_lang(token: contextvars.Token) -> None:
    _current_lang.reset(token)


def current_lang() -> str:
    """Şu anki isteğin dili. Middleware hiç çalışmadıysa (ör. testte doğrudan
    servis fonksiyonu çağrılıyorsa) DEFAULT_LANG'e düşer — asla patlamaz."""
    return _current_lang.get()


def tr_error(message: str, **params: object) -> str:
    """API hata mesajı çevirisi — HTTPException(detail=...) için.

    Frontend'deki gettext deseninin AYNISI: `message` Türkçe kaynak metnin
    kendisidir (aynı zamanda anahtar). `errors_en.ERRORS_EN` içinde karşılığı
    yoksa TR metin DÖNER (ham anahtar/boş kutu değil). `{ad}` biçimli
    yer tutucular varsa `str.format(**params)` ile doldurulur — hem TR hem
    EN metinde AYNI yer tutucu adı kullanılmalı.

    KULLANIM: `raise HTTPException(422, detail=tr_error("Bitiş tarihi başlangıçtan önce olamaz"))`
    Dinamik: `raise HTTPException(422, detail=tr_error("{n} dk sonra tekrar deneyin.", n=5))`
    """
    from app.core.errors_en import ERRORS_EN  # döngüsel import'tan kaçın

    text = ERRORS_EN.get(message, message) if current_lang() == "en" else message
    return text.format(**params) if params else text


def tr_text(message: str, **params: object) -> str:
    """API'nin İÇERİK olarak döndürdüğü metinlerin çevirisi.

    `tr_error` ile aynı gettext deseni, farklı sözlük: hata mesajı bir arıza
    anlatır, buradakiler ürünün normal çıktısıdır (genel skor etiketi, 1:1
    başlıkları, süreç önerileri). Ayrımı korumak, "bu metin nerede görünür"
    sorusunu sözlüğe bakınca cevaplanabilir kılıyor.

    Dili ContextVar'dan okur (LanguageMiddleware): çağıran fonksiyonun
    `request`/`lang` parametresi almasına gerek yok.
    """
    from app.core.texts_en import TEXTS_EN  # döngüsel import'tan kaçın

    text = TEXTS_EN.get(message, message) if current_lang() == "en" else message
    return text.format(**params) if params else text


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
