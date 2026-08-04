"""İŞ-09: kod analizi uzak kaynaklarda (GitHub/GitLab) da diff üretmeli.

ESKİ DAVRANIŞ: diff üretiminin tek yolu yerel git klasörüydü. Repo kaydında
`path` yoksa döngü hiç dönmüyor ve fonksiyon {"status": "ok", "analyzed": 0}
dönüyordu — panoda hata değil, "yeni analiz yok" gibi görünüyordu. Yani özellik
açık, çalışıyor sanılıyor, hiçbir şey yapmıyordu.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest


class _FakeClient:
    """httpx.Client yerine geçer; yol→yanıt sözlüğüyle çalışır, ağa çıkmaz."""

    def __init__(self, yanitlar: dict):
        self.yanitlar = yanitlar
        self.istekler: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, params=None):
        self.istekler.append(url)
        kod, govde = self.yanitlar.get(url, (404, {}))

        class _R:
            status_code = kod

            @staticmethod
            def json():
                return govde

        return _R()


@pytest.fixture()
def github_yanitlari():
    return {
        "/repos/o/r/commits": (200, [{"sha": "abc123"}]),
        "/repos/o/r/commits/abc123": (200, {
            "commit": {"author": {"email": "Dev@Example.com"}, "message": "feat: x"},
            "files": [
                {"filename": "app/a.py", "patch": "@@ -1 +1 @@\n+kod"},
                {"filename": "resim.png"},  # patch yok → ikili dosya, atlanmalı
            ],
        }),
    }


def test_github_diffleri_dosya_bazinda_uretir(monkeypatch, github_yanitlari):
    from app.services import diff_sources

    fake = _FakeClient(github_yanitlari)
    monkeypatch.setattr(diff_sources.httpx, "Client", lambda **kw: fake)
    warnings: list[str] = []

    out = list(diff_sources.iter_github_file_diffs(("o", "r"), "tok", 40, warnings))

    assert warnings == []
    assert len(out) == 1                       # patch'siz dosya üretilmez
    sha, email, mesaj, dosya, diff = out[0]
    assert (sha, dosya) == ("abc123", "app/a.py")
    assert email == "dev@example.com"          # kimlik eşlemesi küçük harf bekler
    assert "kod" in diff


def test_github_hatasi_sessiz_kalmaz(monkeypatch):
    from app.services import diff_sources

    fake = _FakeClient({"/repos/o/r/commits": (401, {})})
    monkeypatch.setattr(diff_sources.httpx, "Client", lambda **kw: fake)
    warnings: list[str] = []

    assert list(diff_sources.iter_github_file_diffs(("o", "r"), None, 40, warnings)) == []
    assert warnings and "401" in warnings[0]


def test_gitlab_diffleri_uretir(monkeypatch):
    from app.services import diff_sources

    fake = _FakeClient({
        "/projects/grup%2Fproje/repository/commits": (
            200, [{"id": "s1", "author_email": "A@B.com", "title": "fix: y"}]),
        "/projects/grup%2Fproje/repository/commits/s1/diff": (
            200, [{"new_path": "src/b.py", "diff": "@@ -1 +1 @@\n+kod"}]),
    })
    monkeypatch.setattr(diff_sources.httpx, "Client", lambda **kw: fake)
    warnings: list[str] = []

    out = list(diff_sources.iter_gitlab_file_diffs(
        "https://gitlab.local", "grup/proje", "tok", 40, warnings))

    assert warnings == []
    assert [(o[0], o[3]) for o in out] == [("s1", "src/b.py")]
    assert out[0][1] == "a@b.com"


def _cfg(provider: str, repos: list[dict]):
    from app.core.config import GitLabSource, GitSource

    git = GitSource(provider=provider, repos=repos)
    if provider == "gitlab":
        git.gitlab = GitLabSource(base_url="https://gitlab.local")
    return SimpleNamespace(sources=SimpleNamespace(git=git))


def test_yerel_path_yoksa_github_yoluna_duser(monkeypatch):
    from app.services import code_analysis, diff_sources

    monkeypatch.setattr(diff_sources.httpx, "Client",
                        lambda **kw: _FakeClient({"/repos/o/r/commits": (200, [])}))
    warnings: list[str] = []
    it = code_analysis._diff_iterator(
        _cfg("github", [{"name": "r", "slug": "o/r"}]), {"name": "r", "slug": "o/r"}, warnings
    )
    assert it is not None
    assert list(it) == []
    assert warnings == []


def test_cozulemeyen_repo_sebebiyle_bildirilir():
    from app.services import code_analysis

    warnings: list[str] = []
    it = code_analysis._diff_iterator(
        _cfg("github", []), {"name": "bozuk", "slug": ""}, warnings
    )
    assert it is None
    assert warnings and "kod analizi" in warnings[0].lower()


def test_kaynaksiz_kurulumda_sonuc_ok_sifir_degil(session, monkeypatch):
    """En kritik regresyon: 'ok/0' demek özelliği çalışıyor sanmaya yol açıyordu."""
    from app.core.config import get_config
    from app.services.code_analysis import run_code_analysis

    cfg = get_config()
    cfg.llm.enabled = True
    cfg.llm.provider = "local"
    cfg.code_analysis.enabled = True
    # path'siz, slug'sız repo: hiçbir kaynaktan diff üretilemez.
    cfg.sources.git.repos = [{"name": "kayip", "team": "T"}]

    out = run_code_analysis(session, cfg)

    assert out["status"] == "no_source"
    assert out["analyzed"] == 0
    assert "note" in out and out["note"]
