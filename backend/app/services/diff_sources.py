"""Kod analizi için diff kaynakları (yerel git / GitHub / GitLab).

NEDEN VAR: kod analizi yalnızca YEREL bir git klasörü okuyabiliyordu
(`iter_git_file_diffs`). `sources.git.provider` github ya da gitlab olduğunda
repo kaydında `path` bulunmadığı için döngü hiç dönmüyor ve fonksiyon
`{"status": "ok", "analyzed": 0}` dönüyordu — panoda hata değil, "yeni analiz
yok" gibi görünüyordu. Özellik açık, çalışıyor sanılıyor, hiçbir şey yapmıyordu.
Kodun kendi notu bu boşluğu "iskele: fetch_gitlab_diff/fetch_github_diff" diye
işaretlemişti; bu modül o iskeleyi gerçek uygulamayla dolduruyor.

Hepsi AYNI şekli üretir: (sha, yazar_epostası, commit_mesajı, dosya, diff).
Böylece run_code_analysis kaynağı bilmeden çalışır.

Hiçbir hata koşuyu düşürmez: sorunlar `warnings` listesine yazılır ve çağıran
bunu kullanıcıya gösterir (sessiz "0 analiz" yerine sebep).
"""
from __future__ import annotations

from collections.abc import Iterator

import httpx

GITHUB_API = "https://api.github.com"


def _hata(warnings: list[str], mesaj: str) -> None:
    if mesaj not in warnings:
        warnings.append(mesaj)


def _durum_mesaji(ad: str, kaynak: str, kod: int, token_env: str) -> str:
    if kod == 404:
        return (f"{kaynak} '{ad}': bulunamadı ya da erişim yok — yol doğru mu, "
                f"{token_env} bu repoyu görüyor mu?")
    if kod == 401:
        return f"{kaynak} '{ad}': {token_env} geçersiz (401)."
    if kod == 403:
        return (f"{kaynak} '{ad}': erişim reddedildi ya da oran sınırı aşıldı (403) — "
                f"{token_env} tanımlı mı?")
    return f"{kaynak} '{ad}': API hatası ({kod})."


def iter_github_file_diffs(
    slug: tuple[str, str],
    token: str | None,
    max_commits: int,
    warnings: list[str],
    token_env: str = "GITHUB_TOKEN",
) -> Iterator[tuple[str, str, str, str, str]]:
    """GitHub'dan son commit'lerin dosya bazlı diff'leri.

    Commit LİSTESİ ucu dosya/patch döndürmez; patch yalnız tek commit ucunda
    gelir. Bu yüzden commit başına bir ek istek atılır — maliyeti sınırlayan
    max_commits (code_analysis.max_files_per_run ile birlikte) bilinçli frendir."""
    owner, repo = slug
    ad = f"{owner}/{repo}"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with httpx.Client(base_url=GITHUB_API, headers=headers, timeout=30.0) as client:
        try:
            resp = client.get(f"/repos/{owner}/{repo}/commits",
                              params={"per_page": min(100, max(1, max_commits))})
        except httpx.HTTPError as e:
            _hata(warnings, f"GitHub '{ad}': ağ hatası ({type(e).__name__}).")
            return
        if resp.status_code != 200:
            _hata(warnings, _durum_mesaji(ad, "GitHub", resp.status_code, token_env))
            return
        for item in resp.json()[:max_commits]:
            sha = item.get("sha") or ""
            if not sha:
                continue
            try:
                detay = client.get(f"/repos/{owner}/{repo}/commits/{sha}")
            except httpx.HTTPError as e:
                _hata(warnings, f"GitHub '{ad}': commit detayı alınamadı ({type(e).__name__}).")
                continue
            if detay.status_code != 200:
                _hata(warnings, _durum_mesaji(ad, "GitHub", detay.status_code, token_env))
                continue
            data = detay.json()
            c = data.get("commit") or {}
            email = ((c.get("author") or {}).get("email") or "").lower()
            mesaj = c.get("message") or ""
            for f in data.get("files") or []:
                patch = f.get("patch")
                # patch YOKSA (ikili dosya ya da çok büyük değişiklik) uydurma:
                # o dosya analiz edilmez.
                if patch and f.get("filename"):
                    yield sha, email, mesaj, f["filename"], patch


def iter_gitlab_file_diffs(
    base_url: str,
    project_path: str,
    token: str | None,
    max_commits: int,
    warnings: list[str],
    token_env: str = "GITLAB_TOKEN",
) -> Iterator[tuple[str, str, str, str, str]]:
    """GitLab'dan son commit'lerin dosya bazlı diff'leri."""
    base = (base_url or "").rstrip("/")
    if not base:
        _hata(warnings, "GitLab adresi (base_url) tanımsız — diff çekilemez.")
        return
    pid = project_path.replace("/", "%2F")
    headers = {"PRIVATE-TOKEN": token} if token else {}
    with httpx.Client(base_url=f"{base}/api/v4", headers=headers, timeout=30.0) as client:
        try:
            resp = client.get(f"/projects/{pid}/repository/commits",
                              params={"per_page": min(100, max(1, max_commits))})
        except httpx.HTTPError as e:
            _hata(warnings, f"GitLab '{project_path}': ağ hatası ({type(e).__name__}).")
            return
        if resp.status_code != 200:
            _hata(warnings, _durum_mesaji(project_path, "GitLab", resp.status_code, token_env))
            return
        for item in resp.json()[:max_commits]:
            sha = item.get("id") or ""
            if not sha:
                continue
            email = (item.get("author_email") or "").lower()
            mesaj = item.get("message") or item.get("title") or ""
            try:
                detay = client.get(f"/projects/{pid}/repository/commits/{sha}/diff")
            except httpx.HTTPError as e:
                _hata(warnings, f"GitLab '{project_path}': diff alınamadı ({type(e).__name__}).")
                continue
            if detay.status_code != 200:
                _hata(warnings,
                      _durum_mesaji(project_path, "GitLab", detay.status_code, token_env))
                continue
            for f in detay.json() or []:
                govde = f.get("diff")
                yol = f.get("new_path") or f.get("old_path")
                if govde and yol:
                    yield sha, email, mesaj, yol, govde
