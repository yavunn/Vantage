"""GitHub adaptörü — takım metrikleri için PR/review verisi.

Bu adaptör var olma sebebi tek başına test edilmeye değer: git_log yerel
klasörü okuduğu için PR diye bir şey göremiyor ve pr_review_time /
review_latency / change_failure_rate kalıcı olarak "veri yetersiz" kalıyordu.

Ağa ÇIKILMAZ: httpx taşıma katmanı sahte yanıtlarla değiştirilir.
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.adapters.github import GitHubProvider, parse_slug


def _sahte_transport(rotalar: dict, cagrilar: list | None = None):
    """rotalar: {path: (status, json)} — path sorgu dizesi HARİÇ eşleşir."""
    def handler(request: httpx.Request) -> httpx.Response:
        if cagrilar is not None:
            cagrilar.append(request.url.path)
        durum, govde = rotalar.get(request.url.path, (404, {"message": "Not Found"}))
        return httpx.Response(durum, content=json.dumps(govde),
                              headers={"content-type": "application/json"})
    return httpx.MockTransport(handler)


@pytest.fixture()
def yamali(monkeypatch):
    """GitHubProvider._client'ı sahte taşıma katmanıyla kurar."""
    def kur(rotalar, cagrilar=None):
        transport = _sahte_transport(rotalar, cagrilar)
        monkeypatch.setattr(
            GitHubProvider, "_client",
            lambda self: httpx.Client(base_url="https://api.github.com", transport=transport),
        )
    return kur


# --- slug çözümleme -----------------------------------------------------------

@pytest.mark.parametrize("giris,beklenen", [
    ("owner/repo", ("owner", "repo")),
    ("https://github.com/owner/repo", ("owner", "repo")),
    ("https://github.com/owner/repo.git", ("owner", "repo")),
    ("git@github.com:owner/repo.git", ("owner", "repo")),
    ("  owner/repo/  ", ("owner", "repo")),
])
def test_slug_cozumleme(giris, beklenen):
    assert parse_slug(giris) == beklenen


def test_slug_cozulemezse_none():
    assert parse_slug("") is None
    assert parse_slug("sadecebirkelime") is None


# --- commit çekme -------------------------------------------------------------

COMMIT_LISTESI = [{
    "sha": "abc123",
    "commit": {
        "message": "feat: yeni özellik",
        "author": {"name": "Ali", "email": "ali@x.com", "date": "2026-07-01T10:00:00Z"},
    },
    "author": {"login": "aliv"},
}]
COMMIT_DETAY = {
    "sha": "abc123",
    "stats": {"additions": 10, "deletions": 3},
    "files": [{"filename": "src/a.py"}, {"filename": "src/b.py"}],
}


def test_commitler_normalize_ediliyor(yamali):
    yamali({
        "/repos/o/r/commits": (200, COMMIT_LISTESI),
        "/repos/o/r/commits/abc123": (200, COMMIT_DETAY),
    })
    p = GitHubProvider([{"name": "nabiz", "slug": "o/r"}])
    commitler = p.fetch_commits()

    assert len(commitler) == 1
    c = commitler[0]
    # repo_name config'teki AD olmalı (slug değil) — repo→takım eşlemesi buna bakar.
    assert c.repo_name == "nabiz"
    assert c.sha == "abc123"
    assert c.author_key == "ali@x.com"
    assert c.committed_at.year == 2026
    # changed_files rework metriği ve hotspot kuralı için ZORUNLU.
    assert c.changed_files == ["src/a.py", "src/b.py"]
    assert (c.additions, c.deletions) == (10, 3)
    assert p.warnings == []


def test_commit_e_postasi_yoksa_hesap_adina_duser(yamali):
    liste = [{
        "sha": "d1",
        "commit": {"message": "m", "author": {"name": "Ali", "date": "2026-07-01T10:00:00Z"}},
        "author": {"login": "aliv"},
    }]
    yamali({"/repos/o/r/commits": (200, liste), "/repos/o/r/commits/d1": (200, COMMIT_DETAY)})
    c = GitHubProvider([{"name": "n", "slug": "o/r"}]).fetch_commits()[0]
    assert c.author_key == "aliv"


def test_detail_limit_sifirsa_detay_istegi_atilmaz(yamali):
    cagrilar: list[str] = []
    yamali({"/repos/o/r/commits": (200, COMMIT_LISTESI)}, cagrilar)
    p = GitHubProvider([{"name": "n", "slug": "o/r"}], detail_limit=0)
    c = p.fetch_commits()[0]

    assert c.changed_files is None  # uydurulmaz, None kalır
    assert "/repos/o/r/commits/abc123" not in cagrilar


# --- hata yolları: senkron ÇÖKMEZ, uyarıya döner -------------------------------

@pytest.mark.parametrize("durum,govde,beklenen_parca", [
    (404, {"message": "Not Found"}, "bulunamadı ya da özel"),
    (401, {"message": "Bad credentials"}, "geçersiz"),
    (403, {"message": "API rate limit exceeded"}, "oran sınırı"),
    (500, {"message": "boom"}, "GitHub API hatası (500)"),
])
def test_api_hatasi_uyariya_donusur_cokmez(yamali, durum, govde, beklenen_parca):
    yamali({"/repos/o/r/commits": (durum, govde)})
    p = GitHubProvider([{"name": "nabiz", "slug": "o/r"}])
    commitler = p.fetch_commits()

    assert commitler == []                       # istisna FIRLATMAZ
    assert len(p.warnings) == 1
    assert beklenen_parca in p.warnings[0]
    assert "nabiz" in p.warnings[0]              # hangi repo olduğu yazmalı


def test_cozulemeyen_slug_uyari_verir(yamali):
    yamali({})
    p = GitHubProvider([{"name": "bozuk", "slug": "???"}])
    assert p.fetch_commits() == []
    assert "çözülemedi" in p.warnings[0]


def test_ayni_uyari_iki_kez_eklenmez(yamali):
    """fetch_commits ve fetch_pull_requests aynı repo listesini çözer."""
    yamali({})
    p = GitHubProvider([{"name": "bozuk", "slug": "???"}])
    p.fetch_commits()
    p.fetch_pull_requests()
    assert len(p.warnings) == 1


# --- PR + review: adaptörün asıl varlık sebebi ---------------------------------

PR_LISTESI = [{
    "number": 7,
    "title": "PR başlığı",
    "user": {"login": "yazar"},
    "created_at": "2026-07-01T09:00:00Z",
    "updated_at": "2026-07-03T09:00:00Z",
    "merged_at": "2026-07-03T09:00:00Z",
    "closed_at": "2026-07-03T09:00:00Z",
}]
REVIEWLAR = [
    # Yazarın kendi review'ı — SAYILMAMALI.
    {"user": {"login": "yazar"}, "submitted_at": "2026-07-01T09:30:00Z", "state": "COMMENTED"},
    {"user": {"login": "gozden"}, "submitted_at": "2026-07-02T12:00:00Z", "state": "APPROVED"},
    {"user": {"login": "ikinci"}, "submitted_at": "2026-07-02T08:00:00Z", "state": "COMMENTED"},
]


def test_pr_ve_reviewlar_cekiliyor(yamali):
    yamali({"/repos/o/r/pulls": (200, PR_LISTESI),
            "/repos/o/r/pulls/7/reviews": (200, REVIEWLAR)})
    prler = GitHubProvider([{"name": "nabiz", "slug": "o/r"}]).fetch_pull_requests()

    assert len(prler) == 1
    pr = prler[0]
    assert pr.repo_name == "nabiz" and pr.external_id == "7"
    assert pr.author_key == "yazar"
    assert pr.merged_at is not None          # deployment_frequency bunu sayar
    # Yazarın kendi yorumu düşmeli: 3 review'dan 2'si kalır.
    assert len(pr.reviews) == 2
    assert {r.reviewer_key for r in pr.reviews} == {"gozden", "ikinci"}
    # first_review_at EN ERKEN review olmalı (liste sırası değil) —
    # review_latency doğrudan buna dayanır.
    assert pr.first_review_at.hour == 8


def test_review_yoksa_first_review_none(yamali):
    yamali({"/repos/o/r/pulls": (200, PR_LISTESI),
            "/repos/o/r/pulls/7/reviews": (200, [])})
    pr = GitHubProvider([{"name": "n", "slug": "o/r"}]).fetch_pull_requests()[0]
    assert pr.first_review_at is None and pr.reviews == []


def test_since_penceresinin_disindaki_pr_atlanir(yamali):
    from datetime import datetime, timezone

    yamali({"/repos/o/r/pulls": (200, PR_LISTESI)})
    p = GitHubProvider([{"name": "n", "slug": "o/r"}])
    sonra = datetime(2026, 8, 1, tzinfo=timezone.utc)  # PR'dan sonrası
    assert p.fetch_pull_requests(since=sonra) == []


def test_review_ucu_patlarsa_pr_yine_doner(yamali):
    """Review çekilemezse PR kaydı kaybolmamalı — cycle/merge verisi değerli."""
    yamali({"/repos/o/r/pulls": (200, PR_LISTESI),
            "/repos/o/r/pulls/7/reviews": (500, {"message": "boom"})})
    prler = GitHubProvider([{"name": "n", "slug": "o/r"}]).fetch_pull_requests()
    assert len(prler) == 1 and prler[0].reviews == []


# --- fabrika + config ---------------------------------------------------------

def test_fabrika_github_saglayicisini_kurar(app_env, monkeypatch):
    import yaml

    from app.adapters.factory import build_git_provider
    from app.core.config import get_config, reset_config_cache

    ham = yaml.safe_load(app_env.read_text(encoding="utf-8"))
    ham["sources"]["git"] = {
        "provider": "github",
        "repos": [{"name": "nabiz", "slug": "o/r", "team": "T"}],
        "github": {"token_env": "TEST_GH_TOKEN", "detail_limit": 5, "max_prs": 9},
    }
    app_env.write_text(yaml.safe_dump(ham, allow_unicode=True), encoding="utf-8")
    monkeypatch.setenv("TEST_GH_TOKEN", "gh-test")
    reset_config_cache()

    p = build_git_provider(get_config())
    assert type(p).__name__ == "GitHubProvider"
    assert p.token == "gh-test"           # sır config'ten DEĞİL, ortamdan
    assert (p.detail_limit, p.max_prs) == (5, 9)
