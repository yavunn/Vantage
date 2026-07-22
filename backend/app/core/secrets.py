"""Sır (token/anahtar) yönetimi — config'ten AYRI.

Tasarım kısıtı: sırlar config.yaml'a ASLA yazılmaz (o dosya paylaşılır/loglanır).
Sırlar ortam değişkeninde yaşar. Bu modül, arayüzden girilen sırları kalıcı
kılmak için gitignore'lu `backend/.secrets.env` dosyasına yazar ve süreç
ortamına (os.environ) canlı uygular — böylece yeniden başlatma gerekmez.

Dosya biçimi basit `NAME=VALUE` satırları (dotenv bağımlılığı yok).
"""
from __future__ import annotations

import os
from pathlib import Path

# backend/ kök dizini (app/core/secrets.py → parents[2])
SECRETS_PATH = Path(__file__).resolve().parents[2] / ".secrets.env"


def _parse(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        out[name.strip()] = value.strip()
    return out


def load_secrets() -> None:
    """Kalıcı sırları ortama yükler. Gerçek ortam değişkenini EZMEZ
    (setdefault): dış env her zaman önceliklidir."""
    for name, value in _parse(SECRETS_PATH).items():
        os.environ.setdefault(name, value)


def set_secret(name: str, value: str) -> None:
    """Bir sırrı hem canlı sürece (os.environ) hem kalıcı dosyaya yazar.
    Boş değer sırrı temizler (dosyadan ve ortamdan siler)."""
    data = _parse(SECRETS_PATH)
    if value:
        os.environ[name] = value
        data[name] = value
    else:
        os.environ.pop(name, None)
        data.pop(name, None)
    lines = [
        "# Otomatik üretildi — sırlar burada tutulur (git'e girmez).",
        *[f"{k}={v}" for k, v in data.items()],
    ]
    SECRETS_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # Dosya izinlerini daralt (best-effort; Windows'ta sessiz geçilebilir).
    try:
        os.chmod(SECRETS_PATH, 0o600)
    except OSError:
        pass
