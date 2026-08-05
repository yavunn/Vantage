"""Sunucu tarafı dil desteği (Accept-Language).

Arayüzü tek başına çevirmek panoyu yarı Türkçe bırakırdı: metrik adları,
açıklamaları ve durum etiketleri API'den geliyor.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(app_env):
    from app.main import app

    return TestClient(app)


def _mk_user(session, email, role="user", password="parola12345"):
    from datetime import datetime, timezone

    from app.core.security import hash_password
    from app.models import User

    now = datetime.now(timezone.utc)
    u = User(email=email.lower(), password_hash=hash_password(password), role=role,
             is_active=True, must_change_password=False, created_at=now, updated_at=now)
    session.add(u)
    session.commit()
    return u


def _token(client, email, password="parola12345"):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_dil_basligi_metrik_adlarini_cevirir(client, session):
    """Arayüzü tek başına çevirmek panoyu yarı Türkçe bırakırdı: metrik adları,
    açıklamaları ve durum etiketleri API'den geliyor."""
    from app.core.config import get_config
    from app.metrics.engine import compute_all
    from tests.conftest import make_team

    team, repo, devs, _ = make_team(session)
    compute_all(session, get_config())
    _mk_user(session, "admin@x.com", role="admin")
    auth = _token(client, "admin@x.com")

    tr = client.get(f"/api/teams/{team.id}/summary",
                    headers={**auth, "Accept-Language": "tr"}).json()
    en = client.get(f"/api/teams/{team.id}/summary",
                    headers={**auth, "Accept-Language": "en-US,en;q=0.9"}).json()

    tr_adlar = {m["key"]: m["name"] for m in tr["metrics"]}
    en_adlar = {m["key"]: m["name"] for m in en["metrics"]}
    assert tr_adlar["deployment_frequency"] == "Teslim Sıklığı"
    assert en_adlar["deployment_frequency"] == "Delivery Frequency"

    tr_etiket = {m["key"]: m["status_label"] for m in tr["metrics"]}
    en_etiket = {m["key"]: m["status_label"] for m in en["metrics"]}
    assert "Veri yetersiz" in tr_etiket.values()
    assert "Not enough data" in en_etiket.values()


def test_desteklenmeyen_dil_turkceye_duser(client, session):
    from app.core.i18n import normalize_lang

    assert normalize_lang("de-DE,de;q=0.9") == "tr"
    assert normalize_lang(None) == "tr"
    assert normalize_lang("en-GB") == "en"


def test_ingilizce_durum_etiketi_ceza_dili_kullanmaz(client, session):
    """Etik çerçeve çeviride de korunmalı: kırmızı bir ceza değil, destek
    çağrısıdır. 'bad' / 'fail' gibi bir performans dili kullanılmaz."""
    from app.core.i18n import status_labels

    en = status_labels("en")
    assert "support" in en["red"].lower()
    for kotu in ("bad", "fail", "poor"):
        assert kotu not in " ".join(en.values()).lower()
