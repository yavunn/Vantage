"""GitHub commit çekme (httpx, GitHub REST API v3).

- Üretim kodu MCP'ye BAĞIMLI DEĞİL: runtime doğrudan REST API'den çeker.
- Token opsiyonel: GITHUB_TOKEN env varsa rate limit artar; public repo tokensiz.
- Ağ/oran/erişim hataları düzgün yükseltilir (çağıran last_status=error yazar).
"""
from __future__ import annotations

import os
import re
from datetime import datetime

import httpx

GITHUB_API = "https://api.github.com"
_URL_RE = re.compile(r"github\.com[/:]([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", re.IGNORECASE)


class GitHubError(Exception):
    pass


def parse_repo(url: str) -> tuple[str, str]:
    """https://github.com/owner/repo(.git) -> (owner, repo). Aksi halde hata."""
    m = _URL_RE.search((url or "").strip())
    if not m:
        raise GitHubError("Geçerli bir GitHub repo adresi değil (https://github.com/kullanici/repo)")
    return m.group(1), m.group(2)


def _headers(token: str | None = None) -> dict:
    """token verilirse O kullanılır (kullanıcının kendi PAT'i), yoksa sunucu
    geneli GITHUB_TOKEN'a düşülür. Sıra önemli: kullanıcının anahtarı her zaman
    kazanmalı ki erişim yarıçapı sunucu token'ı değil KİŞİNİN yetkisi olsun."""
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    tok = token or os.environ.get("GITHUB_TOKEN")
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def _raise_for(resp: httpx.Response, *, kisisel: bool) -> None:
    """HTTP durumunu kullanıcıya gösterilecek Türkçe sebebe çevirir. Mesaj,
    anahtarın kime ait olduğuna göre değişir — "sunucuda token tanımlayın"
    demek, kendi anahtarını girmiş bir çalışan için yanlış yönlendirmedir."""
    if resp.status_code == 404:
        raise GitHubError(
            "Repo bulunamadı ya da erişim izniniz yok. Özel repo ise GitHub "
            "anahtarınızın 'Repository access' listesine bu repoyu ekleyin."
            if kisisel else
            "Repo bulunamadı ya da özel (private) — erişilemiyor"
        )
    if resp.status_code == 403 and "rate limit" in resp.text.lower():
        raise GitHubError(
            "GitHub oran sınırı aşıldı — biraz sonra tekrar deneyin."
            if kisisel else
            "GitHub oran sınırı aşıldı — GITHUB_TOKEN tanımlayın ya da sonra deneyin"
        )
    if resp.status_code == 401:
        raise GitHubError(
            "GitHub anahtarınız geçersiz ya da süresi dolmuş — Ayarlar'dan yenileyin."
            if kisisel else
            "GITHUB_TOKEN geçersiz"
        )
    if resp.status_code != 200:
        raise GitHubError(f"GitHub API hatası ({resp.status_code})")


def check_repo_access(owner: str, repo: str, token: str | None = None) -> dict:
    """Repo bu anahtarla GERÇEKTEN görülebiliyor mu — proje eklemeden önce.

    Yetki doğrulaması budur: kullanıcı yalnız KENDİ anahtarının ulaştığı bir
    repoyu projesi olarak ekleyebilsin. Bu kontrol olmadan, sunucu token'ının
    eriştiği her repo panele girebilen herkese açıktı.
    """
    try:
        with httpx.Client(timeout=20.0) as client:
            resp = client.get(f"{GITHUB_API}/repos/{owner}/{repo}",
                              headers=_headers(token))
    except httpx.HTTPError as e:
        raise GitHubError(f"Ağ hatası: {e}") from e
    _raise_for(resp, kisisel=bool(token))
    body = resp.json()
    return {"private": bool(body.get("private")), "full_name": body.get("full_name")}


def fetch_commits(owner: str, repo: str, max_commits: int = 100,
                  token: str | None = None) -> list[dict]:
    """Son commitleri çeker (en yeni önce). En çok max_commits (tek sayfa 100)."""
    per_page = min(max_commits, 100)
    url = f"{GITHUB_API}/repos/{owner}/{repo}/commits"
    try:
        with httpx.Client(timeout=20.0) as client:
            resp = client.get(url, headers=_headers(token), params={"per_page": per_page})
    except httpx.HTTPError as e:
        raise GitHubError(f"Ağ hatası: {e}") from e

    _raise_for(resp, kisisel=bool(token))

    out = []
    for item in resp.json():
        commit = item.get("commit", {}) or {}
        author = commit.get("author", {}) or {}
        committed_at = None
        if author.get("date"):
            try:
                committed_at = datetime.fromisoformat(author["date"].replace("Z", "+00:00"))
            except ValueError:
                committed_at = None
        out.append({
            "sha": item.get("sha", ""),
            "author_name": author.get("name"),
            "author_email": author.get("email"),
            "message": commit.get("message"),
            "committed_at": committed_at,
        })
    return out
