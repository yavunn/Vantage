"""Kullanıcı başına GitHub anahtarı.

İki güvenlik iddiası test ediliyor:
  1. Anahtar DB'ye düz metin yazılmaz ve hiçbir uçtan geri dönmez.
  2. Kullanıcı yalnız KENDİ anahtarının gördüğü repoyu proje olarak ekleyebilir
     (eskiden sunucu token'ının eriştiği her repo herkese açıktı).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(app_env):
    from app.main import app

    return TestClient(app)


def _mk_user(session, email, role="user", password="parola1"):
    from app.core.security import hash_password
    from app.models import Developer, User

    dev = Developer(display_name=email.split("@")[0], external_ids={}, anonymizable=True)
    session.add(dev)
    session.flush()
    now = datetime.now(timezone.utc)
    u = User(
        email=email.lower(), password_hash=hash_password(password), role=role,
        developer_id=dev.id, is_active=True, must_change_password=False,
        created_at=now, updated_at=now,
    )
    session.add(u)
    session.commit()
    return u


def _auth(client, email, password="parola1"):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# --- şifreleme -----------------------------------------------------------------

def test_anahtar_sifreli_saklanir_ve_geri_donmez(session, monkeypatch):
    from app.services.credentials import get_token, set_token, status

    monkeypatch.delenv("CREDENTIALS_ENC_KEY", raising=False)
    u = _mk_user(session, "u_sifre@corp.local")
    pat = "github_pat_COKGIZLI_1234"

    durum = set_token(session, u.id, pat)
    assert durum["configured"] is True
    assert durum["hint"] == "…1234"          # yalnız son 4
    assert pat not in str(durum)             # anahtar durumda GEÇMEZ

    from app.models import UserCredential

    row = session.scalar(__import__("sqlalchemy").select(UserCredential))
    assert pat not in row.encrypted_value    # DB'de düz metin YOK
    assert get_token(session, u.id) == pat   # ama çözülebiliyor
    assert status(session, u.id)["configured"] is True


def test_bos_deger_baglantiyi_kaldirir(session):
    from app.services.credentials import get_token, set_token

    u = _mk_user(session, "u_sil@corp.local")
    set_token(session, u.id, "github_pat_x1234")
    assert get_token(session, u.id) is not None
    durum = set_token(session, u.id, "")
    assert durum["configured"] is False
    assert get_token(session, u.id) is None


def test_kullanicilar_birbirinin_anahtarini_gormez(session):
    from app.services.credentials import get_token, set_token

    a = _mk_user(session, "u_a@corp.local")
    b = _mk_user(session, "u_b@corp.local")
    set_token(session, a.id, "github_pat_AAAA")
    assert get_token(session, a.id) == "github_pat_AAAA"
    assert get_token(session, b.id) is None   # B'ye sızmıyor


def test_uc_anahtarin_kendisini_dondurmez(client, session):
    _mk_user(session, "u_uc@corp.local")
    h = _auth(client, "u_uc@corp.local")

    r = client.get("/api/me/credentials/github", headers=h)
    assert r.status_code == 200
    assert r.json()["configured"] is False

    # Doğrulama ağa çıkmasın: check_repo_access'i sahtele.
    import app.api.credentials as mod

    mod.check_repo_access = lambda *a, **k: {"private": False, "full_name": "github/docs"}
    r = client.put("/api/me/credentials/github",
                   json={"token": "github_pat_GERCEK_9999"}, headers=h)
    assert r.status_code == 200
    govde = r.json()
    assert govde["configured"] is True and govde["hint"] == "…9999"
    assert "GERCEK" not in r.text          # anahtar yanıtta YOK

    assert "GERCEK" not in client.get("/api/me/credentials/github", headers=h).text


# --- yetki doğrulaması ---------------------------------------------------------

def test_kendi_anahtarinin_gormedigi_repo_eklenemez(client, session, monkeypatch):
    """Eski davranış: sunucu token'ı görüyorsa herkes ekleyebiliyordu."""
    import app.api.projects as pmod
    from app.services.github import GitHubError

    _mk_user(session, "u_yetki@corp.local")

    def _erisim_yok(owner, repo, token=None):
        raise GitHubError("Repo bulunamadı ya da erişim izniniz yok.")

    monkeypatch.setattr(pmod, "check_repo_access", _erisim_yok)
    r = client.post("/api/projects",
                    json={"name": "Baskasinin", "github_url": "https://github.com/biri/gizli"},
                    headers=_auth(client, "u_yetki@corp.local"))
    assert r.status_code == 422
    assert "erişim izniniz yok" in r.json()["detail"]


def test_erisilebilen_repo_eklenir_ve_sahibin_anahtariyla_cekilir(
    client, session, monkeypatch,
):
    """Senkron, tetikleyenin değil PROJE SAHİBİNİN anahtarını kullanmalı."""
    import app.api.projects as pmod
    from app.services.credentials import set_token

    u = _mk_user(session, "u_sahip@corp.local")
    set_token(session, u.id, "github_pat_SAHIP")

    kullanilan: list = []

    monkeypatch.setattr(pmod, "check_repo_access",
                        lambda owner, repo, token=None: {"private": True, "full_name": f"{owner}/{repo}"})

    def _fetch(owner, repo, max_commits=100, token=None):
        kullanilan.append(token)
        return [{"sha": "abc123", "author_name": "Yazan", "author_email": "y@x.local",
                 "message": "gizli commit", "committed_at": datetime.now(timezone.utc)}]

    monkeypatch.setattr(pmod, "fetch_commits", _fetch)

    r = client.post("/api/projects",
                    json={"name": "Kendi", "github_url": "https://github.com/u/gizli"},
                    headers=_auth(client, "u_sahip@corp.local"))
    assert r.status_code == 201, r.text
    assert r.json()["commit_count"] == 1
    assert kullanilan == ["github_pat_SAHIP"]   # sunucu token'ı DEĞİL
