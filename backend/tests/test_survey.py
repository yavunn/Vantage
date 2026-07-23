"""Anonim memnuniyet anketi — anonimlik + şifreleme + k-eşiği testleri.

Doğrulananlar:
- Cevap kaydında kullanıcı kimliği KOLONU yok; payload şifreli (düz metin DB'de
  bulunmuyor). Cevap ile katılım JOIN edilip kişi-cevap eşleşmesi üretilemiyor.
- Aynı user aynı döngü 2. kez -> 409.
- k-eşiği altında maskeli, üstünde agrega doğru.
- SURVEY_ENC_KEY yoksa POST 503, düz metin yazılmıyor.
- Admin ucu ham per-cevap döndürmüyor. genkey yalnız owner.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(app_env):
    from app.main import app

    return TestClient(app)


def _mk_user(session, email, role="user", *, is_owner=False, password="parola1"):
    from app.core.security import hash_password
    from app.models import Developer, User

    dev = Developer(display_name=email.split("@")[0], external_ids={}, anonymizable=True)
    session.add(dev)
    session.flush()
    now = datetime.now(timezone.utc)
    u = User(
        email=email.lower(), password_hash=hash_password(password), role=role,
        is_owner=is_owner, developer_id=dev.id, is_active=True,
        must_change_password=False, created_at=now, updated_at=now,
    )
    session.add(u)
    session.commit()
    return u


def _token(client, email, password="parola1"):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture()
def survey_on(monkeypatch):
    """Anketi aç + geçerli şifreleme anahtarı ver."""
    from app.core.config import get_config
    from app.core.survey_crypto import SURVEY_KEY_ENV, generate_key

    monkeypatch.setenv(SURVEY_KEY_ENV, generate_key())
    get_config().survey.enabled = True
    yield


# --- anonimlik: şema düzeyi -------------------------------------------------

def test_cevap_tablosunda_kullanici_kolonu_yok(app_env):
    from sqlalchemy import inspect
    from app.core.db import get_engine
    import app.models  # noqa: F401

    cols = {c["name"] for c in inspect(get_engine()).get_columns("survey_responses")}
    # Kişiye bağlayacak HİÇBİR kolon olmamalı.
    assert "user_id" not in cols
    assert "developer_id" not in cols
    assert cols == {"id", "cycle_id", "ciphertext", "schema_version"}


# --- gönderim: anonim + şifreli --------------------------------------------

def test_gonderim_sifreli_ve_anonim(client, session, survey_on):
    _mk_user(session, "emp@x.com")
    t = _token(client, "emp@x.com")

    secret_comment = "GIZLI-YORUM-abc123-benim-imzam"
    r = client.post("/api/survey/current",
                    json={"answers": {"workload": 4, "team": 5, "management": 3,
                                      "growth": 2, "overall": 4},
                          "comment": secret_comment},
                    headers=_auth(t))
    assert r.status_code == 200, r.text

    from app.models import SurveyResponse, SurveyParticipation
    resp = session.scalars(__import__("sqlalchemy").select(SurveyResponse)).all()
    assert len(resp) == 1
    # Düz metin DB'de bulunmamalı — payload şifreli.
    assert secret_comment not in resp[0].ciphertext
    # Cevap satırında kişiye işaret eden alan yok (yalnız cycle + şifre).
    assert not hasattr(resp[0], "user_id")
    # Katılım defteri kişiyi tutar ama CEVABI değil.
    parts = session.scalars(__import__("sqlalchemy").select(SurveyParticipation)).all()
    assert len(parts) == 1 and parts[0].user_id is not None
    # İki tabloyu birleştirecek ortak/sıralı anahtar yok: response'ta cycle_id var
    # ama user yok; participation'da user var ama response'a bağ yok.
    assert not hasattr(parts[0], "response_id")


def test_ayni_donem_ikinci_gonderim_409(client, session, survey_on):
    _mk_user(session, "emp@x.com")
    t = _token(client, "emp@x.com")
    body = {"answers": {"workload": 3, "team": 3, "management": 3, "growth": 3, "overall": 3}}
    assert client.post("/api/survey/current", json=body, headers=_auth(t)).status_code == 200
    r2 = client.post("/api/survey/current", json=body, headers=_auth(t))
    assert r2.status_code == 409


def test_anahtar_yoksa_503_ve_kayit_yok(client, session, monkeypatch):
    from app.core.config import get_config
    from app.core.survey_crypto import SURVEY_KEY_ENV

    monkeypatch.delenv(SURVEY_KEY_ENV, raising=False)
    get_config().survey.enabled = True
    _mk_user(session, "emp@x.com")
    t = _token(client, "emp@x.com")
    r = client.post("/api/survey/current",
                    json={"answers": {"workload": 3}}, headers=_auth(t))
    assert r.status_code == 503
    from app.models import SurveyResponse
    assert session.scalars(__import__("sqlalchemy").select(SurveyResponse)).all() == []


# --- admin: agrega + k-eşiği ------------------------------------------------

def _submit_n(client, session, n, base=3):
    for i in range(n):
        _mk_user(session, f"u{i}@x.com")
        t = _token(client, f"u{i}@x.com")
        client.post("/api/survey/current",
                    json={"answers": {"workload": base, "team": base, "management": base,
                                      "growth": base, "overall": base}},
                    headers=_auth(t))


def test_esik_altinda_maskeli(client, session, survey_on):
    _mk_user(session, "admin@x.com", role="admin")
    _submit_n(client, session, 2)  # min_responses=4 altında
    at = _token(client, "admin@x.com")
    r = client.get("/api/survey/results", headers=_auth(at))
    assert r.status_code == 200
    data = r.json()
    assert data["masked"] is True
    assert "scores" not in data and "comments" not in data
    assert data["response_count"] == 2


def test_esik_ustunde_agrega_dogru(client, session, survey_on):
    _mk_user(session, "admin@x.com", role="admin")
    _submit_n(client, session, 4, base=4)
    at = _token(client, "admin@x.com")
    data = client.get("/api/survey/results", headers=_auth(at)).json()
    assert data["masked"] is False
    workload = next(s for s in data["scores"] if s["key"] == "workload")
    assert workload["average"] == 4.0 and workload["count"] == 4
    assert workload["distribution"]["4"] == 4
    # Ham per-cevap yok; yalnız agrega + (varsa) karışık yorum listesi.
    assert set(workload.keys()) == {"key", "average", "count", "distribution"}


def test_calisan_results_goremez_403(client, session, survey_on):
    _mk_user(session, "emp@x.com")
    t = _token(client, "emp@x.com")
    assert client.get("/api/survey/results", headers=_auth(t)).status_code == 403


def test_genkey_yalniz_owner(client, session, monkeypatch, tmp_path):
    # Gerçek .secrets.env'i kirletme + gerçek env'i ezme: izole et.
    from app.core import secrets as secrets_mod
    from app.core.survey_crypto import SURVEY_KEY_ENV

    monkeypatch.setattr(secrets_mod, "SECRETS_PATH", tmp_path / ".secrets.env")
    monkeypatch.delenv(SURVEY_KEY_ENV, raising=False)
    _mk_user(session, "owner@x.com", role="admin", is_owner=True)
    _mk_user(session, "admin@x.com", role="admin")
    assert client.post("/api/survey/genkey", headers=_auth(_token(client, "admin@x.com"))).status_code == 403
    r = client.post("/api/survey/genkey", headers=_auth(_token(client, "owner@x.com")))
    assert r.status_code == 200 and r.json()["key_configured"] is True
    assert (tmp_path / ".secrets.env").read_text(encoding="utf-8").find(SURVEY_KEY_ENV) >= 0
