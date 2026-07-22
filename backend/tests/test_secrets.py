"""Sır yönetimi (.secrets.env) — arayüzden girilen token'lar için.

Sır config'e YAZILMAZ; gitignore'lu dosya + ortam değişkeni. Bu modül dosyaya
yazar, ortama uygular ve gerçek env'i EZMEZ (setdefault)."""
from __future__ import annotations

import os

import app.core.secrets as secrets


def test_set_ve_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(secrets, "SECRETS_PATH", tmp_path / ".secrets.env")
    monkeypatch.delenv("TRELLO_KEY", raising=False)

    secrets.set_secret("TRELLO_KEY", "abc123")
    # Canlı ortama hemen uygulanır.
    assert os.environ["TRELLO_KEY"] == "abc123"
    # Dosyaya yazıldı (config'e değil).
    assert "TRELLO_KEY=abc123" in (tmp_path / ".secrets.env").read_text(encoding="utf-8")

    # Ortamı temizle, load ile geri gelsin.
    monkeypatch.delenv("TRELLO_KEY", raising=False)
    secrets.load_secrets()
    assert os.environ["TRELLO_KEY"] == "abc123"


def test_load_gercek_envi_ezmez(tmp_path, monkeypatch):
    monkeypatch.setattr(secrets, "SECRETS_PATH", tmp_path / ".secrets.env")
    secrets.set_secret("TRELLO_TOKEN", "dosyadaki")
    # Dış ortam değişkeni her zaman önceliklidir.
    monkeypatch.setenv("TRELLO_TOKEN", "gercek-env")
    secrets.load_secrets()
    assert os.environ["TRELLO_TOKEN"] == "gercek-env"


def test_bos_deger_sirri_siler(tmp_path, monkeypatch):
    monkeypatch.setattr(secrets, "SECRETS_PATH", tmp_path / ".secrets.env")
    secrets.set_secret("TRELLO_KEY", "xyz")
    secrets.set_secret("TRELLO_KEY", "")
    assert "TRELLO_KEY" not in os.environ
    assert "TRELLO_KEY" not in (tmp_path / ".secrets.env").read_text(encoding="utf-8")
