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


def _headers() -> dict:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def fetch_commits(owner: str, repo: str, max_commits: int = 100) -> list[dict]:
    """Son commitleri çeker (en yeni önce). En çok max_commits (tek sayfa 100)."""
    per_page = min(max_commits, 100)
    url = f"{GITHUB_API}/repos/{owner}/{repo}/commits"
    try:
        with httpx.Client(timeout=20.0) as client:
            resp = client.get(url, headers=_headers(), params={"per_page": per_page})
    except httpx.HTTPError as e:
        raise GitHubError(f"Ağ hatası: {e}") from e

    if resp.status_code == 404:
        raise GitHubError("Repo bulunamadı ya da özel (private) — erişilemiyor")
    if resp.status_code == 403 and "rate limit" in resp.text.lower():
        raise GitHubError("GitHub oran sınırı aşıldı — GITHUB_TOKEN tanımlayın ya da sonra deneyin")
    if resp.status_code == 401:
        raise GitHubError("GITHUB_TOKEN geçersiz")
    if resp.status_code != 200:
        raise GitHubError(f"GitHub API hatası ({resp.status_code})")

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
