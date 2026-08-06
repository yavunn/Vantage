"""API hata mesajı çevirisi (tr_error + LanguageMiddleware).

Bu mekanizma öncekilerden FARKLI: metrik adları/durum etiketleri gibi bir
FastAPI dependency (`lang_from_request`) ile değil, isteğin başında bir
ContextVar'a yazılan dille çalışıyor — çünkü `HTTPException(detail=...)`
yüzlerce çağrı noktasında ve her birine `request: Request` eklemek pratik
değildi. FastAPI senkron path fonksiyonlarını bir threadpool'a (anyio.to_thread)
taşıdığı için, ContextVar'ın gerçekten o thread'e de taşındığını — yani
mekanizmanın gerçek bir istek/yanıt döngüsünde çalıştığını — burada kanıtlıyoruz.
Ayrıca: bir isteğin dili bir SONRAKİ isteğe SIZMAMALI (thread yeniden kullanılsa
bile) — ardışık TR/EN isteğiyle test edilir.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(app_env):
    from app.main import app

    return TestClient(app)


def test_hata_mesaji_varsayilan_turkce(client):
    r = client.post("/api/auth/login", json={"email": "yok@x.com", "password": "yanlis"})
    assert r.status_code == 401
    assert r.json()["detail"] == "E-posta ya da parola hatalı"


def test_hata_mesaji_accept_language_ile_ingilizceye_ceviriliyor(client):
    r = client.post(
        "/api/auth/login", json={"email": "yok@x.com", "password": "yanlis"},
        headers={"Accept-Language": "en-US,en;q=0.9"},
    )
    assert r.status_code == 401
    assert r.json()["detail"] == "Incorrect email or password"


def test_dil_bir_istekten_digerine_sizmiyor(client):
    """ContextVar sıfırlanmazsa ASGI sunucusunun thread'i yeniden kullanması
    durumunda bir isteğin dili sonrakine sızardı — ardışık TR/EN/TR isteğiyle
    doğrulanır (TestClient art arda çağrılar aynı thread havuzunu kullanabilir)."""
    en = client.post("/api/auth/login", json={"email": "x@x.com", "password": "y"},
                     headers={"Accept-Language": "en"})
    assert en.json()["detail"] == "Incorrect email or password"

    tr = client.post("/api/auth/login", json={"email": "x@x.com", "password": "y"})
    assert tr.json()["detail"] == "E-posta ya da parola hatalı"

    en2 = client.post("/api/auth/login", json={"email": "x@x.com", "password": "y"},
                      headers={"Accept-Language": "en"})
    assert en2.json()["detail"] == "Incorrect email or password"


def test_eksik_ceviri_turkceye_duser():
    """`ERRORS_EN`'de karşılığı olmayan bir mesaj — ham anahtar/boş kutu değil,
    Türkçe metnin kendisi dönmeli (frontend'deki gettext kuralının aynısı)."""
    from app.core.i18n import reset_current_lang, set_current_lang, tr_error

    token = set_current_lang("en")
    try:
        assert tr_error("Kataloğa hiç girmeyen bir test mesajı") == "Kataloğa hiç girmeyen bir test mesajı"
    finally:
        reset_current_lang(token)


def test_parametreli_mesaj_dolduruluyor():
    from app.core.errors_en import ERRORS_EN
    from app.core.i18n import reset_current_lang, set_current_lang, tr_error

    ERRORS_EN["{n} dk sonra tekrar deneyin."] = "Try again in {n} minutes."
    token = set_current_lang("en")
    try:
        assert tr_error("{n} dk sonra tekrar deneyin.", n=5) == "Try again in 5 minutes."
    finally:
        reset_current_lang(token)
        del ERRORS_EN["{n} dk sonra tekrar deneyin."]
