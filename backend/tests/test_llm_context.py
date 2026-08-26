"""İŞ-08: yerel LLM bağlam sınırı — sessiz kesilme regresyonu.

ÖLÇÜLEN SORUN: /v1/chat/completions ucu `options` kabul etmediği için num_ctx
gönderilemiyordu; Ollama varsayılan 4096 token'a düşüp prompt'un BAŞINI atıyordu.
Config'in kendi sınırıyla (max_diff_lines=400) üretilen gerçek bir analiz
prompt'u ~7.700 token iken uç 2050 token gördü — model diff'in dörtte birini
görüp yine de 7 boyutta puan üretti. Kesilme sessiz olduğu için sonuç "çalışıyor"
görünüyordu.
"""
from __future__ import annotations

import pytest

from app.core.config import LLMLocal
from app.llm import local_client
from app.llm.local_client import (
    ContextOverflowError,
    estimate_tokens,
    fit_to_budget,
    local_chat,
    prompt_budget,
)


class _Post:
    """httpx.post yerine geçer; gönderileni saklar, ağa çıkmaz."""

    def __init__(self, govde: dict):
        self.govde = govde
        self.url = None
        self.json = None
        self.headers = None

    def __call__(self, url, **kw):
        self.url, self.json, self.headers = url, kw.get("json"), kw.get("headers")
        govde = self.govde

        class _R:
            @staticmethod
            def raise_for_status():
                return None

            @staticmethod
            def json():
                return govde

        return _R()


def _ollama_govde(prompt_eval_count=10_000):
    return {"message": {"content": "cevap"}, "prompt_eval_count": prompt_eval_count}


def test_ollama_stilinde_num_ctx_gercekten_gonderilir(monkeypatch):
    """ASIL DÜZELTME: bağlam uzunluğu uca bildiriliyor mu."""
    post = _Post(_ollama_govde())
    monkeypatch.setattr(local_client.httpx, "post", post)
    local = LLMLocal(base_url="http://uc.local", model="m", context_tokens=16384)

    local_chat(local, "sistem", "soru")

    assert post.url.endswith("/api/chat"), "ollama stilinde /api/chat kullanılmalı"
    assert post.json["options"]["num_ctx"] == 16384
    assert post.json["stream"] is False


def test_openai_stilinde_eski_uc_korunur(monkeypatch):
    """vLLM/OpenRouter/OpenAI kullanıcıları kırılmamalı."""
    post = _Post({"choices": [{"message": {"content": "cevap"}}],
                  "usage": {"prompt_tokens": 10_000}})
    monkeypatch.setattr(local_client.httpx, "post", post)
    local = LLMLocal(base_url="http://uc.local", model="m", api_style="openai")

    local_chat(local, "sistem", "soru")

    assert post.url.endswith("/v1/chat/completions")
    assert "options" not in post.json


def test_butceyi_asan_prompt_gonderilmeden_once_kirpilir(monkeypatch):
    """Kesilme uçta SESSİZCE değil, burada BEYAN edilerek olmalı."""
    post = _Post(_ollama_govde(prompt_eval_count=10_000))
    monkeypatch.setattr(local_client.httpx, "post", post)
    local = LLMLocal(base_url="http://uc.local", model="m",
                     context_tokens=2048, reserve_output_tokens=512)

    dev_metin = "satır\n" * 20_000
    sonuc = local_chat(local, "sistem", dev_metin)

    assert sonuc.truncated is True
    gonderilen = post.json["messages"][-1]["content"]
    assert len(gonderilen) < len(dev_metin)
    assert "kısaltıldı" in gonderilen  # model "devamı vardı"yı görüyor
    assert estimate_tokens(gonderilen) <= prompt_budget(local)


def test_butceye_sigan_prompt_kirpilmaz(monkeypatch):
    post = _Post(_ollama_govde(prompt_eval_count=10_000))
    monkeypatch.setattr(local_client.httpx, "post", post)
    local = LLMLocal(base_url="http://uc.local", model="m")

    sonuc = local_chat(local, "sistem", "kısa soru")

    assert sonuc.truncated is False
    assert post.json["messages"][-1]["content"] == "kısa soru"


def test_uc_prompt_un_tamamini_gormediyse_hata(monkeypatch):
    """Ayarlara rağmen uç kendi sınırına takılırsa (ör. OLLAMA_CONTEXT_LENGTH)
    bu sessiz kalmamalı: eksik girdiye dayanan puan güvenilir değildir."""
    # ~3000 token gönderiyoruz ama uç yalnız 2050 gördüğünü bildiriyor.
    post = _Post(_ollama_govde(prompt_eval_count=2050))
    monkeypatch.setattr(local_client.httpx, "post", post)
    local = LLMLocal(base_url="http://uc.local", model="m", context_tokens=16384)

    with pytest.raises(ContextOverflowError) as e:
        local_chat(local, "sistem", "x" * 30_000)
    assert "2050" in str(e.value)


def test_baglam_tasmasi_kullaniciya_net_sebep_olur():
    from app.services.code_analysis import classify_error

    mesaj = classify_error(ContextOverflowError("uç prompt'un yalnız 2050 token'ını gördü"))
    assert "bağlam sınırı" in mesaj
    # Sebep kullanıcıya gider: config alan adı değil, nereden düzelteceği yazar.
    assert "context_tokens" not in mesaj


def test_token_tahmini_olculen_orana_yakin():
    """Tahmin ÖLÇÜMLE kalibre edildi: qwen2.5:14b üzerinde gerçek bir 400 satırlık
    analiz prompt'u 30.766 karakterdi ve uç 15.296 token saydı (2,01 kar/token).
    Tahmin bunun ALTINA düşerse (token sayısını az tahmin edersek) bütçeye
    sığdığını sanıp uca fazla veri göndeririz — düzeltilen sessiz kesilme geri gelir."""
    olculen_karakter, olculen_token = 30_766, 15_296
    tahmin = estimate_tokens("x" * olculen_karakter)
    assert tahmin >= olculen_token, "token sayısı EKSİK tahmin ediliyor"
    assert tahmin <= olculen_token * 1.3, "aşırı tahmin bağlamı gereksiz daraltır"


def test_fit_to_budget_sinirlari():
    metin = "a" * 10_000
    kisa, kirpildi = fit_to_budget(metin, 10)
    assert kirpildi is True
    assert len(kisa) < len(metin)
    ayni, kirpildi2 = fit_to_budget("kısa", 1000)
    assert (ayni, kirpildi2) == ("kısa", False)


def test_turkce_metinde_yanlis_kesilme_alarmi_verilmez(monkeypatch):
    """GERÇEK OLAY: iş↔commit analizi hiç çalışmıyordu.

    Türkçe düzyazı ~3 karakter/token paketlenir; bütçeleme için ölçülen 2,0
    kar/token oranı bu metinde token sayısını FAZLA tahmin ediyor. Alarm eşiği
    o tahmine bakınca (1.048 gerçek < 1.555 tahmin × 0,8) "prompt kesildi"
    diyordu — oysa num_ctx 16.384 iken 1.000 token'lık bir prompt'un kesilmesi
    fiziksel olarak mümkün değil. Kıyas artık ALT SINIRLA yapılıyor.
    """
    metin = "a" * 3_100          # ~1.555 token TAHMİN, alt sınır 775
    post = _Post(_ollama_govde(prompt_eval_count=1048))
    monkeypatch.setattr(local_client.httpx, "post", post)
    local = LLMLocal(base_url="http://uc.local", model="m", context_tokens=16384)

    sonuc = local_chat(local, "sistem", metin)

    assert sonuc.prompt_tokens == 1048   # hata YOK, analiz üretilebilir


def test_gercek_kesilme_hala_yakalanir(monkeypatch):
    """Yanlış alarmı susturmak, asıl korumayı kaldırmamalı: ölçülen olayda
    30.768 karakter gönderilmiş, uç 2.050 token görmüştü."""
    post = _Post(_ollama_govde(prompt_eval_count=2050))
    monkeypatch.setattr(local_client.httpx, "post", post)
    local = LLMLocal(base_url="http://uc.local", model="m", context_tokens=16384)

    with pytest.raises(ContextOverflowError):
        local_chat(local, "sistem", "x" * 30_768)


def test_zaman_asimi_configten_gelir(monkeypatch):
    """120 sn SABİTTİ: 14B model CPU'da soğuk başlatma (~23 sn) + üretim
    (30-38 sn ölçüldü) üst üste gelince ilk istek ReadTimeout'a düşüyordu."""
    from app.llm.advisor import LocalAdvisor

    yakalanan = {}

    def sahte(local, system, user, api_key=None, timeout=None, max_output_tokens=None):
        yakalanan["timeout"] = timeout
        return local_client.LocalChatResult(text="ok", prompt_tokens=10,
                                            sent_chars=10, truncated=False)

    monkeypatch.setattr("app.llm.advisor.local_chat", sahte)
    local = LLMLocal(base_url="http://uc.local", model="m", timeout_seconds=450)

    LocalAdvisor(local).chat("sistem", "soru")

    assert yakalanan["timeout"] == 450
