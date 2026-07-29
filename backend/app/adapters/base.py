"""Adaptör arayüzleri ve normalize DTO'lar.

Adaptör deseni ZORUNLUDUR (spec Bölüm 3): her kaynak (git, gitlab, jira,
trello) tek bir ortak arayüzü uygular. Yeni kaynak eklemek çekirdeği
bozmaz; kirli/eksik alanlar tek yerde (ingest servisi) ele alınır.

Adaptörler DB'ye dokunmaz — yalnızca normalize DTO listeleri döner.
Tüm DTO alanları Optional'dır: adaptör eksik alanı None bırakır,
UYDURMAZ. Metrik motoru None'u görüp o kaydı ilgili metrikten düşer ve
completeness oranına yansıtır.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

# --- Normalize DTO'lar (ortak şemanın taşıma hâli) ---------------------------

@dataclass
class NormalizedCommit:
    repo_name: str
    sha: str
    author_key: str | None = None          # kaynak-içi kimlik (email vb.)
    author_name: str | None = None
    committed_at: datetime | None = None
    message: str | None = None
    changed_files: list[str] | None = None
    additions: int | None = None
    deletions: int | None = None


@dataclass
class NormalizedReview:
    reviewer_key: str | None = None
    reviewed_at: datetime | None = None


@dataclass
class NormalizedPR:
    repo_name: str
    external_id: str
    author_key: str | None = None
    author_name: str | None = None
    title: str | None = None
    opened_at: datetime | None = None
    first_review_at: datetime | None = None
    merged_at: datetime | None = None
    closed_at: datetime | None = None
    reviews: list[NormalizedReview] = field(default_factory=list)


@dataclass
class NormalizedTransition:
    from_status: str | None
    to_status: str
    changed_at: datetime


@dataclass
class NormalizedTask:
    source: str                             # jira | trello | fixture
    external_id: str
    team_name: str | None = None
    assignee_key: str | None = None
    assignee_name: str | None = None
    title: str | None = None
    type: str | None = None                 # story | bug | task
    status: str | None = None
    created_at: datetime | None = None
    # Katman 2 — çoğu zaman boş gelir, boş kalır:
    estimate_hours: float | None = None
    due_date: datetime | None = None
    story_points: float | None = None
    transitions: list[NormalizedTransition] = field(default_factory=list)


# --- Sağlayıcı arayüzleri -----------------------------------------------------

@runtime_checkable
class GitProvider(Protocol):
    """Katman 0 — her zaman var olan, kimsenin elle girmediği veri."""

    def fetch_commits(self, since: datetime | None = None) -> list[NormalizedCommit]: ...
    def fetch_pull_requests(self, since: datetime | None = None) -> list[NormalizedPR]: ...


@runtime_checkable
class TaskProvider(Protocol):
    """Katman 1+2 — Jira ve Trello bu tek arayüzün arkasındadır."""

    def fetch_tasks(self, since: datetime | None = None) -> list[NormalizedTask]: ...
