"""GitLab API GitProvider'ı (şirket GitLab'ı — on-prem).

Commit + Merge Request (PR) verisini çeker. Token config'e yazılmaz,
ortam değişkeninden okunur. API hatası tüm senkronu düşürmez.
"""
from __future__ import annotations

import os
from datetime import datetime

import httpx

from app.adapters.base import NormalizedCommit, NormalizedPR, NormalizedReview


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class GitLabProvider:
    def __init__(self, base_url: str, token_env: str, projects: list[str],
                 token: str | None = None):
        """token verilirse doğrudan kullanılır (Faz 4: kullanıcı projesinin
        decrypt edilmiş credential'ı); verilmezse env'den okunur."""
        self.base_url = base_url.rstrip("/")
        self.token = token if token is not None else os.environ.get(token_env, "")
        self.projects = projects  # "grup/proje" yolları ya da sayısal id'ler

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=f"{self.base_url}/api/v4",
            headers={"PRIVATE-TOKEN": self.token},
            timeout=30,
        )

    def _paged(self, client: httpx.Client, url: str, params: dict) -> list[dict]:
        items: list[dict] = []
        page = 1
        while True:
            resp = client.get(url, params={**params, "per_page": 100, "page": page})
            if resp.status_code != 200:
                break  # tek proje hatası senkronu durdurmaz
            batch = resp.json()
            if not batch:
                break
            items.extend(batch)
            if resp.headers.get("x-next-page") in (None, ""):
                break
            page += 1
        return items

    def fetch_commits(self, since: datetime | None = None) -> list[NormalizedCommit]:
        out: list[NormalizedCommit] = []
        params: dict = {"with_stats": "true"}
        if since:
            params["since"] = since.isoformat()
        with self._client() as client:
            for proj in self.projects:
                pid = str(proj).replace("/", "%2F")
                for c in self._paged(client, f"/projects/{pid}/repository/commits", params):
                    stats = c.get("stats") or {}
                    out.append(
                        NormalizedCommit(
                            repo_name=str(proj),
                            sha=c.get("id", ""),
                            author_key=c.get("author_email"),
                            author_name=c.get("author_name"),
                            committed_at=_dt(c.get("committed_date")),
                            message=c.get("title"),
                            changed_files=None,  # ayrı istek gerekir; opsiyonel bırakıldı
                            additions=stats.get("additions"),
                            deletions=stats.get("deletions"),
                        )
                    )
        return out

    def fetch_pull_requests(self, since: datetime | None = None) -> list[NormalizedPR]:
        out: list[NormalizedPR] = []
        params: dict = {"state": "all"}
        if since:
            params["updated_after"] = since.isoformat()
        with self._client() as client:
            for proj in self.projects:
                pid = str(proj).replace("/", "%2F")
                for mr in self._paged(client, f"/projects/{pid}/merge_requests", params):
                    author = mr.get("author") or {}
                    # İlk review yaklaşımı: notes API'sinden ilk insan yorumu
                    first_review_at = None
                    reviews: list[NormalizedReview] = []
                    notes = self._paged(
                        client,
                        f"/projects/{pid}/merge_requests/{mr.get('iid')}/notes",
                        {"sort": "asc"},
                    )
                    for note in notes:
                        if note.get("system"):
                            continue
                        note_author = (note.get("author") or {}).get("username")
                        if note_author == author.get("username"):
                            continue  # yazarın kendi yorumu review sayılmaz
                        ts = _dt(note.get("created_at"))
                        if ts:
                            reviews.append(NormalizedReview(reviewer_key=note_author, reviewed_at=ts))
                            if first_review_at is None:
                                first_review_at = ts
                    out.append(
                        NormalizedPR(
                            repo_name=str(proj),
                            external_id=str(mr.get("iid")),
                            author_key=author.get("username"),
                            author_name=author.get("name"),
                            title=mr.get("title"),
                            opened_at=_dt(mr.get("created_at")),
                            first_review_at=first_review_at,
                            merged_at=_dt(mr.get("merged_at")),
                            closed_at=_dt(mr.get("closed_at")),
                            reviews=reviews,
                        )
                    )
        return out
