"""Etik çerçeve testleri (spec Bölüm 1 + İlke E — pazarlıksız).

- Bireysel görünüm: yalnız kişinin kendisi + yöneticisi (kimlik JWT'den).
- Leaderboard ucu yok.
- Anonimleştirme modu: isimler maskelenir, bireysel uçlar kapanır.
- LLM katmanı varsayılan kapalı: veri dışarı gitmez.
- Dashboard uçları GEÇERLİ JWT ister (tokensiz 401) — kimlik artık taklit
  edilebilen X-Dev-Id değil, JWT'dir.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from tests.conftest import make_team


@pytest.fixture()
def client(app_env):
    from app.main import app

    return TestClient(app)


def _mk_user(session, dev, email, role="user", password="parola1"):
    from app.core.security import hash_password
    from app.models import User

    now = datetime.now(timezone.utc)
    u = User(
        email=email.lower(), password_hash=hash_password(password), role=role,
        developer_id=dev.id, is_active=True, must_change_password=False,
        created_at=now, updated_at=now,
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


def test_bireysel_gorunum_kisinin_kendisine_acik(client, session):
    team, repo, devs, mgr = make_team(session)
    _mk_user(session, devs[0], "u0@x.com")
    t0 = _token(client, "u0@x.com")
    resp = client.get(f"/api/developers/{devs[0].id}/summary", headers=_auth(t0))
    assert resp.status_code == 200, resp.text
    assert resp.json()["developer"]["id"] == devs[0].id


def test_bireysel_gorunum_baska_gelistiriciye_kapali(client, session):
    team, repo, devs, mgr = make_team(session)
    _mk_user(session, devs[1], "u1@x.com")
    t1 = _token(client, "u1@x.com")
    # u1, devs[0]'ı görmeye çalışır → 403 (kendisi/yöneticisi değil).
    resp = client.get(f"/api/developers/{devs[0].id}/summary", headers=_auth(t1))
    assert resp.status_code == 403


def test_bireysel_gorunum_yoneticiye_acik(client, session):
    team, repo, devs, mgr = make_team(session)
    _mk_user(session, mgr, "mgr@x.com")
    tm = _token(client, "mgr@x.com")
    resp = client.get(f"/api/developers/{devs[0].id}/summary", headers=_auth(tm))
    assert resp.status_code == 200


def test_kimliksiz_istek_reddedilir(client, session):
    team, repo, devs, mgr = make_team(session)
    # Token yok → router seviyesinde 401.
    resp = client.get(f"/api/developers/{devs[0].id}/summary")
    assert resp.status_code == 401


def test_leaderboard_ucu_yok(client, session):
    """Kıyaslamalı sıralama ucu bilinçli olarak yoktur (Bölüm 1)."""
    from app.main import app

    paths = {getattr(r, "path", "") for r in app.routes}
    assert not any("leaderboard" in p or "ranking" in p for p in paths)
    # directory ucu metrik İÇERMEZ (isim listesi + metrik = leaderboard olur)
    team, repo, devs, mgr = make_team(session)
    _mk_user(session, devs[0], "u0@x.com")
    t0 = _token(client, "u0@x.com")
    body = client.get("/api/directory", headers=_auth(t0)).json()
    assert all("value" not in d and "metrics" not in d for d in body)


def test_anonimlestirme_modu(client, session, app_env):
    """IK 'isim istemiyoruz' derse: takım-agregat mod (İlke E)."""
    from app.core.config import reset_config_cache

    team, repo, devs, mgr = make_team(session)
    _mk_user(session, devs[0], "u0@x.com")
    t0 = _token(client, "u0@x.com")
    text = app_env.read_text(encoding="utf-8").replace(
        "anonymize_individuals: false", "anonymize_individuals: true"
    )
    app_env.write_text(text, encoding="utf-8")
    reset_config_cache()

    # İsimler maskelenir
    body = client.get("/api/directory", headers=_auth(t0)).json()
    assert all(d["display_name"].startswith("Geliştirici #") for d in body)
    # Bireysel uç tamamen kapanır — kişinin kendisi bile göremez
    resp = client.get(f"/api/developers/{devs[0].id}/summary", headers=_auth(t0))
    assert resp.status_code == 403


def test_llm_varsayilan_kapali(client, session):
    """On-prem kısıtı: dışarı veri gönderen katman bilinçli açılmadıkça 503."""
    team, repo, devs, mgr = make_team(session)
    _mk_user(session, devs[0], "u0@x.com")
    t0 = _token(client, "u0@x.com")
    resp = client.get(f"/api/teams/{team.id}/ai-advice", headers=_auth(t0))
    assert resp.status_code == 503


def test_takim_gorunumu_girisli_kullaniciya_acik(client, session):
    """Takım-agregat görünüm her GİRİŞLİ kullanıcıya açık; tokensiz 401."""
    team, repo, devs, mgr = make_team(session)
    _mk_user(session, devs[0], "u0@x.com")
    t0 = _token(client, "u0@x.com")
    resp = client.get(f"/api/teams/{team.id}/summary", headers=_auth(t0))
    assert resp.status_code == 200
    assert resp.json()["team"]["name"] == team.name
    # Tokensiz erişim reddedilir (artık public değil).
    assert client.get(f"/api/teams/{team.id}/summary").status_code == 401
