"""Etik çerçeve testleri (spec Bölüm 1 + İlke E — pazarlıksız).

- Bireysel görünüm: yalnız kişinin kendisi + yöneticisi.
- Leaderboard ucu yok.
- Anonimleştirme modu: isimler maskelenir, bireysel uçlar kapanır.
- LLM katmanı varsayılan kapalı: veri dışarı gitmez.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import make_team


@pytest.fixture()
def client(app_env):
    from app.main import app

    return TestClient(app)


def test_bireysel_gorunum_kisinin_kendisine_acik(client, session):
    team, repo, devs, mgr = make_team(session)
    resp = client.get(f"/api/developers/{devs[0].id}/summary",
                      headers={"X-Dev-Id": str(devs[0].id)})
    assert resp.status_code == 200
    assert resp.json()["developer"]["id"] == devs[0].id


def test_bireysel_gorunum_baska_gelistiriciye_kapali(client, session):
    team, repo, devs, mgr = make_team(session)
    resp = client.get(f"/api/developers/{devs[0].id}/summary",
                      headers={"X-Dev-Id": str(devs[1].id)})
    assert resp.status_code == 403


def test_bireysel_gorunum_yoneticiye_acik(client, session):
    team, repo, devs, mgr = make_team(session)
    resp = client.get(f"/api/developers/{devs[0].id}/summary",
                      headers={"X-Dev-Id": str(mgr.id)})
    assert resp.status_code == 200


def test_kimliksiz_istek_reddedilir(client, session):
    team, repo, devs, mgr = make_team(session)
    resp = client.get(f"/api/developers/{devs[0].id}/summary")
    assert resp.status_code == 401


def test_leaderboard_ucu_yok(client, session):
    """Kıyaslamalı sıralama ucu bilinçli olarak yoktur (Bölüm 1)."""
    from app.main import app

    paths = {getattr(r, "path", "") for r in app.routes}
    assert not any("leaderboard" in p or "ranking" in p for p in paths)
    # directory ucu metrik İÇERMEZ (isim listesi + metrik = leaderboard olur)
    team, repo, devs, mgr = make_team(session)
    body = client.get("/api/directory").json()
    assert all("value" not in d and "metrics" not in d for d in body)


def test_anonimlestirme_modu(client, session, app_env):
    """IK 'isim istemiyoruz' derse: takım-agregat mod (İlke E)."""
    from app.core.config import reset_config_cache

    team, repo, devs, mgr = make_team(session)
    text = app_env.read_text(encoding="utf-8").replace(
        "anonymize_individuals: false", "anonymize_individuals: true"
    )
    app_env.write_text(text, encoding="utf-8")
    reset_config_cache()

    # İsimler maskelenir
    body = client.get("/api/directory").json()
    assert all(d["display_name"].startswith("Geliştirici #") for d in body)
    # Bireysel uç tamamen kapanır — kişinin kendisi bile göremez
    resp = client.get(f"/api/developers/{devs[0].id}/summary",
                      headers={"X-Dev-Id": str(devs[0].id)})
    assert resp.status_code == 403


def test_llm_varsayilan_kapali(client, session):
    """On-prem kısıtı: dışarı veri gönderen katman bilinçli açılmadıkça 503."""
    team, repo, devs, mgr = make_team(session)
    resp = client.get(f"/api/teams/{team.id}/ai-advice")
    assert resp.status_code == 503


def test_takim_gorunumu_herkese_acik(client, session):
    team, repo, devs, mgr = make_team(session)
    resp = client.get(f"/api/teams/{team.id}/summary")
    assert resp.status_code == 200
    assert resp.json()["team"]["name"] == team.name
