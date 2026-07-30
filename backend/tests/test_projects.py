"""Projeler: admin proje EKLEYEMEZ ama TÜM kullanıcı projelerini görür."""
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


def _token(client, email, password="parola1"):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


def _add_project(session, user_id, name="P1"):
    from app.models import UserProject

    now = datetime.now(timezone.utc)
    p = UserProject(
        user_id=user_id, project_name=name, source_type="github",
        source_url="https://github.com/a/b", created_at=now, updated_at=now,
    )
    session.add(p)
    session.commit()
    return p


def test_admin_proje_ekleyemez(client, session):
    _mk_user(session, "admin@x.com", role="admin")
    at = _token(client, "admin@x.com")
    r = client.post("/api/projects",
                    json={"name": "X", "github_url": "https://github.com/x/y"},
                    headers=_auth(at))
    assert r.status_code == 403


def test_admin_tum_projeleri_gorur(client, session):
    u = _mk_user(session, "u@x.com")
    _mk_user(session, "admin@x.com", role="admin")
    _add_project(session, u.id, "P1")

    at = _token(client, "admin@x.com")
    rows = client.get("/api/projects", headers=_auth(at)).json()
    assert len(rows) == 1 and rows[0]["name"] == "P1"
    assert "owner" in rows[0]  # admin sahibi de görür

    # kullanıcı yalnız kendininki (owner alanı yok)
    ut = _token(client, "u@x.com")
    urows = client.get("/api/projects", headers=_auth(ut)).json()
    assert len(urows) == 1 and "owner" not in urows[0]


# --- Yerel klasör kaynağı (gizli repolar için: token yok, ağ yok) --------------

def _local_repo(tmp_path, ad="gizli-proje", mesaj="ilk commit"):
    import subprocess

    p = tmp_path / ad
    p.mkdir(parents=True, exist_ok=True)
    def run(*a):
        subprocess.run(["git", "-C", str(p), *a], capture_output=True, check=True)
    run("init", "-q")
    run("config", "user.email", "kod@ornek.local")
    run("config", "user.name", "Kod Yazan")
    (p / "a.txt").write_text("icerik\n", encoding="utf-8")
    run("add", ".")
    run("commit", "-q", "-m", mesaj)
    return p


def _izinli_kok_yap(kok):
    """Test config'ine projects.local_roots ekler ve önbelleği düşürür."""
    import os
    from pathlib import Path

    from app.core.config import reset_config_cache

    cfg_file = Path(os.environ["VANTAGE_CONFIG"])
    cfg_file.write_text(
        cfg_file.read_text(encoding="utf-8")
        + f'\nprojects:\n  local_roots:\n    - "{Path(kok).as_posix()}"\n',
        encoding="utf-8",
    )
    reset_config_cache()


def test_yerel_kaynak_kapaliyken_proje_eklenemez(client, session, tmp_path):
    """Varsayılan kapalı — yönetici izinli kök tanımlamadan kullanılamaz."""
    _mk_user(session, "u_kapali@corp.local")
    repo = _local_repo(tmp_path / "kok")
    r = client.post("/api/projects",
                    json={"name": "P", "source_type": "local", "local_path": str(repo)},
                    headers=_auth(_token(client, "u_kapali@corp.local")))
    assert r.status_code == 422
    assert "kapalı" in r.json()["detail"]


def test_yerel_kaynak_izinli_kokte_calisir_ve_commit_ceker(client, session, tmp_path):
    kok = tmp_path / "kok"
    repo = _local_repo(kok, mesaj="feat: gizli repo commiti")
    _izinli_kok_yap(kok)
    _mk_user(session, "u_yerel@corp.local")

    r = client.post("/api/projects",
                    json={"name": "Gizli", "source_type": "local", "local_path": str(repo)},
                    headers=_auth(_token(client, "u_yerel@corp.local")))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["source_type"] == "local"
    assert body["commit_count"] == 1        # ilk senkron yerel git'ten okudu
    assert body["last_status"] == "ok"

    commits = client.get(f"/api/projects/{body['id']}/commits",
                         headers=_auth(_token(client, "u_yerel@corp.local"))).json()
    assert any("gizli repo commiti" in (c.get("message") or "") for c in commits)


def test_yerel_kaynak_izinli_kok_disina_cikamaz(client, session, tmp_path):
    """Kullanıcı sunucudaki rastgele bir depoyu proje diye ekleyememeli."""
    kok = tmp_path / "kok"
    _local_repo(kok, ad="icerdeki")
    baskasinin = _local_repo(tmp_path, ad="baskasinin-reposu")
    _izinli_kok_yap(kok)
    _mk_user(session, "u_kacis@corp.local")

    r = client.post("/api/projects",
                    json={"name": "Kaçış", "source_type": "local",
                          "local_path": str(baskasinin)},
                    headers=_auth(_token(client, "u_kacis@corp.local")))
    assert r.status_code == 422
    assert "izinli kökler dışında" in r.json()["detail"]


def test_yerel_kaynakta_da_admin_proje_ekleyemez(client, session, tmp_path):
    kok = tmp_path / "kok"
    repo = _local_repo(kok)
    _izinli_kok_yap(kok)
    _mk_user(session, "admin_yerel@corp.local", role="admin")

    r = client.post("/api/projects",
                    json={"name": "P", "source_type": "local", "local_path": str(repo)},
                    headers=_auth(_token(client, "admin_yerel@corp.local")))
    assert r.status_code == 403


def test_gecersiz_source_type_reddedilir(client, session):
    _mk_user(session, "u_gecersiz@corp.local")
    r = client.post("/api/projects",
                    json={"name": "P", "source_type": "ftp", "local_path": "/x"},
                    headers=_auth(_token(client, "u_gecersiz@corp.local")))
    assert r.status_code == 422


def test_source_type_gonderilmezse_github_varsayilir(client, session):
    """Geriye uyum: eski istemci yalnız name + github_url gönderiyordu."""
    _mk_user(session, "u_eski@corp.local")
    r = client.post("/api/projects",
                    json={"name": "P", "github_url": "not-a-url"},
                    headers=_auth(_token(client, "u_eski@corp.local")))
    # github yolundan doğrulanmalı (URL hatası), source_type hatası DEĞİL
    assert r.status_code == 422
    assert "GitHub repo adresi" in r.json()["detail"]
