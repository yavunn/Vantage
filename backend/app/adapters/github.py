"""GitHub API GitProvider'ı (Faz 4 — kullanıcı projeleri).

Commit + Pull Request verisini çeker. Token doğrudan verilir (kullanıcının
şifreli credential'ından decrypt edilmiş hâli) — URL'ye/log'a yazılmaz,
yalnız Authorization başlığında taşınır. API hatası senkronu düşürmez.
"""
from __future__ import annotations

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


class GitHubProvider:
    def __init__(self, api_base: str, repo_full_name: str, token: str,
                 repo_name: str | None = None):
        """api_base: https://api.github.com ya da GH Enterprise /api/v3.
        repo_full_name: "org/repo". repo_name: DB'de görünecek ad
        (verilmezse repo_full_name)."""
        self.api_base = api_base.rstrip("/")
        self.repo_full_name = repo_full_name
        self.token = token
        self.repo_name = repo_name or repo_full_name

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.api_base,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=30,
        )

    def _paged(self, client: httpx.Client, url: str, params: dict) -> list[dict]:
        items: list[dict] = []
        page = 1
        while True:
            resp = client.get(url, params={**params, "per_page": 100, "page": page})
            if resp.status_code != 200:
                break  # tek istek hatası senkronu durdurmaz
            batch = resp.json()
            if not isinstance(batch, list) or not batch:
                break
            items.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return items

    def fetch_commits(self, since: datetime | None = None) -> list[NormalizedCommit]:
        params: dict = {}
        if since:
            params["since"] = since.isoformat()
        out: list[NormalizedCommit] = []
        with self._client() as client:
            for c in self._paged(client, f"/repos/{self.repo_full_name}/commits", params):
                commit = c.get("commit") or {}
                author = commit.get("author") or {}
                out.append(
                    NormalizedCommit(
                        repo_name=self.repo_name,
                        sha=c.get("sha", ""),
                        author_key=author.get("email"),
                        author_name=author.get("name"),
                        committed_at=_dt(author.get("date")),
                        message=commit.get("message"),
                        # Liste API'si dosya/satır vermez; alan None kalır,
                        # UYDURULMAZ — ilgili metrik completeness'e yansır.
                        changed_files=None,
                        additions=None,
                        deletions=None,
                    )
                )
        return out

    def fetch_pull_requests(self, since: datetime | None = None) -> list[NormalizedPR]:
        out: list[NormalizedPR] = []
        with self._client() as client:
            pulls = self._paged(
                client, f"/repos/{self.repo_full_name}/pulls",
                {"state": "all", "sort": "updated", "direction": "desc"},
            )
            for pr in pulls:
                if since and _dt(pr.get("updated_at")) and _dt(pr.get("updated_at")) < since:
                    continue
                author = (pr.get("user") or {}).get("login")
                number = pr.get("number")
                first_review_at = None
                reviews: list[NormalizedReview] = []
                for rv in self._paged(
                    client, f"/repos/{self.repo_full_name}/pulls/{number}/reviews", {}
                ):
                    reviewer = (rv.get("user") or {}).get("login")
                    if reviewer == author:
                        continue  # yazarın kendi yorumu review sayılmaz
                    ts = _dt(rv.get("submitted_at"))
                    if ts:
                        reviews.append(NormalizedReview(reviewer_key=reviewer, reviewed_at=ts))
                        if first_review_at is None or ts < first_review_at:
                            first_review_at = ts
                out.append(
                    NormalizedPR(
                        repo_name=self.repo_name,
                        external_id=str(number),
                        author_key=author,
                        author_name=author,
                        title=pr.get("title"),
                        opened_at=_dt(pr.get("created_at")),
                        first_review_at=first_review_at,
                        merged_at=_dt(pr.get("merged_at")),
                        closed_at=_dt(pr.get("closed_at")),
                        reviews=reviews,
                    )
                )
        return out
