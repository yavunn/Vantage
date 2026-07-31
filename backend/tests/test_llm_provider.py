"""AI sağlayıcı yönetimi — yalnız baş yönetici (owner) yetkisi + davranış.

- GET/PUT /api/admin/llm-provider yalnız owner: admin/hr/user = 403.
- Owner sağlayıcıyı ve modeli config'e yazar; API anahtarı .secrets.env'e (config'e
  ASLA). Anahtarın kendisi GET'te dönmez — yalnız 'tanımlı mı' durumu.
- provider=local anahtarsız da hazır sayılır (Ollama vb.).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(app_env):
    from app.main import app

    return TestClient(app)


def _mk_user(session, email, role, *, is_owner=False, password="parola1"):
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


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def actors(client, session):
    _mk_user(session, "owner@x.com", "admin", is_owner=True)
    _mk_user(session, "admin@x.com", "admin")
    _mk_user(session, "emp@x.com", "user")
    return {
        "owner_t": _token(client, "owner@x.com"),
        "admin_t": _token(client, "admin@x.com"),
        "emp_t": _token(client, "emp@x.com"),
    }


def test_llm_provider_get_yalniz_owner(client, actors):
    assert client.get("/api/admin/llm-provider", headers=_auth(actors["owner_t"])).status_code == 200
    assert client.get("/api/admin/llm-provider", headers=_auth(actors["admin_t"])).status_code == 403
    assert client.get("/api/admin/llm-provider", headers=_auth(actors["emp_t"])).status_code == 403


def test_llm_provider_put_yalniz_owner(client, actors):
    body = {"provider": "local"}
    assert client.put("/api/admin/llm-provider", json=body, headers=_auth(actors["admin_t"])).status_code == 403
    assert client.put("/api/admin/llm-provider", json=body, headers=_auth(actors["emp_t"])).status_code == 403


def test_owner_saglayici_secip_model_yazar(client, actors):
    r = client.put(
        "/api/admin/llm-provider",
        json={"provider": "local", "local_base_url": "http://localhost:1234",
              "local_model": "qwen2.5-coder"},
        headers=_auth(actors["owner_t"]),
    )
    assert r.status_code == 200, r.text
    got = client.get("/api/admin/llm-provider", headers=_auth(actors["owner_t"])).json()
    assert got["provider"] == "local"
    assert got["local"]["base_url"] == "http://localhost:1234"
    assert got["local"]["model"] == "qwen2.5-coder"
    # Gerçek sağlayıcı seçmek modülü açar (ayrı 'enabled' kutucuğu yok).
    assert got["enabled"] is True
    ca = client.get("/api/admin/code-analysis", headers=_auth(actors["admin_t"])).json()
    assert ca["llm_enabled"] is True and ca["enabled"] is True


def test_none_saglayici_modulu_kapatir(client, actors):
    # Önce aç, sonra none ile kapat.
    client.put("/api/admin/llm-provider", json={"provider": "claude"},
               headers=_auth(actors["owner_t"]))
    r = client.put("/api/admin/llm-provider", json={"provider": "none"},
                   headers=_auth(actors["owner_t"]))
    assert r.status_code == 200
    got = client.get("/api/admin/llm-provider", headers=_auth(actors["owner_t"])).json()
    assert got["provider"] == "none" and got["enabled"] is False


def test_gecersiz_saglayici_422(client, actors):
    r = client.put("/api/admin/llm-provider", json={"provider": "gpt"},
                   headers=_auth(actors["owner_t"]))
    assert r.status_code == 422


def test_api_anahtari_config_e_yazilmaz_env_e_yazilir(client, actors, monkeypatch, tmp_path):
    from app.core import secrets as secrets_mod

    # .secrets.env'i geçici dizine yönlendir (gerçek dosyayı kirletme).
    monkeypatch.setattr(secrets_mod, "SECRETS_PATH", tmp_path / ".secrets.env")

    r = client.put(
        "/api/admin/llm-provider",
        json={"provider": "claude", "claude_model": "claude-sonnet-5",
              "claude_api_key": "sk-test-12345"},
        headers=_auth(actors["owner_t"]),
    )
    assert r.status_code == 200, r.text

    # Anahtar env'e işlenir + kalıcı dosyaya yazılır.
    import os
    assert os.environ.get("ANTHROPIC_API_KEY") == "sk-test-12345"
    assert "sk-test-12345" in (tmp_path / ".secrets.env").read_text(encoding="utf-8")

    # config.yaml'a anahtar SIZMAZ.
    from pathlib import Path

    from app.core.config import DEFAULT_CONFIG_PATH
    cfg_path = os.environ.get("VANTAGE_CONFIG") or str(DEFAULT_CONFIG_PATH)
    assert "sk-test-12345" not in Path(cfg_path).read_text(encoding="utf-8")

    # GET anahtarın kendisini dönmez, yalnız 'tanımlı' durumunu.
    got = client.get("/api/admin/llm-provider", headers=_auth(actors["owner_t"])).json()
    assert got["claude"]["api_key"]["configured"] is True
    assert "sk-test-12345" not in str(got)


# --- yerel uçta kimlik doğrulama ----------------------------------------------
# REGRESYON: LocalAdvisor bu başlığı hiç göndermiyordu. Arayüz yerel API anahtarı
# kaydetmeye izin verdiği ve LocalAnalyzer anahtarı KULLANDIĞI için, base_url
# anahtar isteyen bir uca (OpenAI/OpenRouter) çevrildiğinde kod analizi çalışıp
# öneri/RAG'ın 401 alması gibi açıklanamaz bir bölünme oluşuyordu.


class _CapturingPost:
    """httpx.post yerine geçer; gönderilen başlıkları saklar, ağa çıkmaz."""

    def __init__(self):
        self.headers: dict | None = None

    def __call__(self, url, **kwargs):
        self.headers = kwargs.get("headers")

        class _Resp:
            @staticmethod
            def raise_for_status():
                return None

            @staticmethod
            def json():
                return {"choices": [{"message": {"content": "cevap"}}]}

        return _Resp()


def _local_cfg(api_key_env: str):
    from types import SimpleNamespace

    return SimpleNamespace(llm=SimpleNamespace(
        enabled=True, provider="local",
        local=SimpleNamespace(
            base_url="http://uc.local", model="m", api_key_env=api_key_env,
        ),
    ))


def test_yerel_advisor_anahtar_varsa_authorization_gonderir(monkeypatch):
    from app.llm import advisor as advisor_mod

    post = _CapturingPost()
    monkeypatch.setattr(advisor_mod.httpx, "post", post)
    advisor_mod.LocalAdvisor("http://uc.local", "m", "sk-yerel").chat("sistem", "soru")
    assert post.headers == {"Authorization": "Bearer sk-yerel"}


def test_yerel_advisor_anahtarsiz_ucta_baslik_gondermez(monkeypatch):
    from app.llm import advisor as advisor_mod

    post = _CapturingPost()
    monkeypatch.setattr(advisor_mod.httpx, "post", post)
    advisor_mod.LocalAdvisor("http://uc.local", "m").chat("sistem", "soru")
    # Ollama anahtar istemez; boş Bearer göndermek bazı uçlarda 401 sebebidir.
    assert post.headers == {}


def test_build_advisor_yerel_anahtari_ortamdan_okur(monkeypatch):
    from app.llm import advisor as advisor_mod

    monkeypatch.setenv("TEST_LOCAL_LLM_KEY", "sk-ortam")
    post = _CapturingPost()
    monkeypatch.setattr(advisor_mod.httpx, "post", post)
    advisor_mod.build_advisor(_local_cfg("TEST_LOCAL_LLM_KEY")).chat("", "soru")
    assert post.headers == {"Authorization": "Bearer sk-ortam"}


def test_yerel_advisor_rag_sohbetiyle_ayni_yolu_kullanir(monkeypatch):
    """advise() de chat() üzerinden geçer — anahtar iki yolda da gider."""
    from app.llm import advisor as advisor_mod

    monkeypatch.setenv("TEST_LOCAL_LLM_KEY", "sk-ortam")
    post = _CapturingPost()
    monkeypatch.setattr(advisor_mod.httpx, "post", post)
    advisor_mod.build_advisor(_local_cfg("TEST_LOCAL_LLM_KEY")).advise("Takım", "metrik")
    assert post.headers == {"Authorization": "Bearer sk-ortam"}
