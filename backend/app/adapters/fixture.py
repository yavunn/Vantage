"""JSON fixture dosyalarından okuyan adaptörler.

İki amaç:
1. Gerçek API erişimi olmadan geliştirme/demo (spec Bölüm 6).
2. Seed script'in ürettiği sentetik kirli veriyi normal ingest hattından
   geçirmek — böylece "kirli veriye dayanıklılık" gerçek pipeline'da test edilir.

Dosya formatı: DTO alanlarıyla bire bir JSON. Tarihler ISO-8601 string.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.adapters.base import (
    NormalizedCommit,
    NormalizedPR,
    NormalizedQualitySnapshot,
    NormalizedReview,
    NormalizedTask,
    NormalizedTransition,
)


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class FixtureGitProvider:
    def __init__(self, fixture_dir: str | Path):
        self.dir = Path(fixture_dir)

    def fetch_commits(self, since: datetime | None = None) -> list[NormalizedCommit]:
        return [
            NormalizedCommit(
                repo_name=c["repo_name"],
                sha=c["sha"],
                author_key=c.get("author_key"),
                author_name=c.get("author_name"),
                committed_at=_dt(c.get("committed_at")),
                message=c.get("message"),
                changed_files=c.get("changed_files"),
                additions=c.get("additions"),
                deletions=c.get("deletions"),
            )
            for c in _load(self.dir / "commits.json")
        ]

    def fetch_pull_requests(self, since: datetime | None = None) -> list[NormalizedPR]:
        return [
            NormalizedPR(
                repo_name=p["repo_name"],
                external_id=str(p["external_id"]),
                author_key=p.get("author_key"),
                author_name=p.get("author_name"),
                title=p.get("title"),
                opened_at=_dt(p.get("opened_at")),
                first_review_at=_dt(p.get("first_review_at")),
                merged_at=_dt(p.get("merged_at")),
                closed_at=_dt(p.get("closed_at")),
                reviews=[
                    NormalizedReview(r.get("reviewer_key"), _dt(r.get("reviewed_at")))
                    for r in p.get("reviews", [])
                ],
            )
            for p in _load(self.dir / "pull_requests.json")
        ]


class FixtureTaskProvider:
    def __init__(self, fixture_dir: str | Path):
        self.dir = Path(fixture_dir)

    def fetch_tasks(self, since: datetime | None = None) -> list[NormalizedTask]:
        return [
            NormalizedTask(
                source=t.get("source", "fixture"),
                external_id=str(t["external_id"]),
                team_name=t.get("team_name"),
                assignee_key=t.get("assignee_key"),
                assignee_name=t.get("assignee_name"),
                title=t.get("title"),
                type=t.get("type"),
                status=t.get("status"),
                created_at=_dt(t.get("created_at")),
                estimate_hours=t.get("estimate_hours"),
                due_date=_dt(t.get("due_date")),
                story_points=t.get("story_points"),
                transitions=[
                    NormalizedTransition(tr.get("from_status"), tr["to_status"], ts)
                    for tr in t.get("transitions", [])
                    if (ts := _dt(tr.get("changed_at"))) is not None
                ],
            )
            for t in _load(self.dir / "tasks.json")
        ]


class FixtureQualityProvider:
    def __init__(self, fixture_dir: str | Path):
        self.dir = Path(fixture_dir)

    def fetch_snapshots(self) -> list[NormalizedQualitySnapshot]:
        return [
            NormalizedQualitySnapshot(
                repo_name=s["repo_name"],
                taken_at=_dt(s.get("taken_at")) or datetime.now().astimezone(),
                coverage=s.get("coverage"),
                complexity=s.get("complexity"),
                duplication=s.get("duplication"),
                code_smells=s.get("code_smells"),
            )
            for s in _load(self.dir / "quality.json")
        ]
