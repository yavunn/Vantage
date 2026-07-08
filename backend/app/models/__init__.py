"""Ortak normalize veri modeli (spec Bölüm 4).

Tüm kaynaklar (git, jira, trello, sonarqube) bu şemaya normalize edilir.
Kural: alanlar nullable'dır — eksik alan ilgili metriği devre dışı bırakır,
sistemi asla çökertmez (İlke A: kirli veri hata değil, ana özelliktir).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)

    memberships: Mapped[list["TeamMembership"]] = relationship(back_populates="team")
    repos: Mapped[list["Repo"]] = relationship(back_populates="team")


class Developer(Base):
    __tablename__ = "developers"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Farklı kaynaklardaki kimlikler: {"git": "a@x.com", "jira": "akey", ...}
    external_ids: Mapped[dict] = mapped_column(JSON, default=dict)
    display_name: Mapped[str] = mapped_column(String(200))
    # İlke E: kimlik bir katman arkasında — anonimleştirme modunda display_name
    # yerine bu takma ad gösterilir. Kişi bazında da maskelenebilir.
    anonymizable: Mapped[bool] = mapped_column(Boolean, default=True)

    memberships: Mapped[list["TeamMembership"]] = relationship(back_populates="developer")


class User(Base):
    """Giriş hesabı (Faz 1). Developer = metrik/veri varlığı, User = kimlik;
    ikisi developer_id ile bağlanır, alanlar çoğaltılmaz. Parola yalnızca
    bcrypt hash olarak tutulur; plain parola hiçbir yerde saklanmaz."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), default="user")  # admin | user
    developer_id: Mapped[int | None] = mapped_column(
        ForeignKey("developers.id"), nullable=True, unique=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    developer: Mapped[Developer | None] = relationship()


class UserProject(Base):
    """Kullanıcının bağladığı dış kaynak (Faz 3). repo_id: analiz (Faz 4)
    veriyi mevcut Repo/Commit modeline yazar — ayrı veri adası yoktur."""

    __tablename__ = "user_projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    project_name: Mapped[str] = mapped_column(String(200))
    source_type: Mapped[str] = mapped_column(String(50))  # github | gitlab | jira | trello
    source_url: Mapped[str] = mapped_column(String(500))
    repo_id: Mapped[int | None] = mapped_column(ForeignKey("repos.id"), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user: Mapped[User] = relationship()
    credential: Mapped["ProjectCredential | None"] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class ProjectCredential(Base):
    """Bağlı kaynağın erişim token'ı — YALNIZ Fernet ile şifreli saklanır.
    Plain token DB'ye, log'a, response'a ve URL'ye asla yazılmaz."""

    __tablename__ = "project_credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("user_projects.id"), unique=True
    )
    encrypted_value: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    project: Mapped[UserProject] = relationship(back_populates="credential")


class TeamMembership(Base):
    __tablename__ = "team_memberships"
    __table_args__ = (UniqueConstraint("team_id", "developer_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    developer_id: Mapped[int] = mapped_column(ForeignKey("developers.id"))
    role: Mapped[str] = mapped_column(String(50), default="member")  # member | manager

    team: Mapped[Team] = relationship(back_populates="memberships")
    developer: Mapped[Developer] = relationship(back_populates="memberships")


class Repo(Base):
    __tablename__ = "repos"

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(300), unique=True)

    team: Mapped[Team | None] = relationship(back_populates="repos")


class Commit(Base):
    __tablename__ = "commits"
    __table_args__ = (UniqueConstraint("repo_id", "sha"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id"))
    sha: Mapped[str] = mapped_column(String(64))
    author_id: Mapped[int | None] = mapped_column(ForeignKey("developers.id"), nullable=True)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Değişen dosya yolları — rework/hotspot analizi için (JSON listesi)
    changed_files: Mapped[list | None] = mapped_column(JSON, nullable=True)
    additions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deletions: Mapped[int | None] = mapped_column(Integer, nullable=True)


class PullRequest(Base):
    __tablename__ = "pull_requests"
    __table_args__ = (UniqueConstraint("repo_id", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id"))
    external_id: Mapped[str] = mapped_column(String(100))
    author_id: Mapped[int | None] = mapped_column(ForeignKey("developers.id"), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    reviews: Mapped[list["PRReview"]] = relationship(back_populates="pull_request")


class PRReview(Base):
    __tablename__ = "pr_reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    pr_id: Mapped[int] = mapped_column(ForeignKey("pull_requests.id"))
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("developers.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    pull_request: Mapped[PullRequest] = relationship(back_populates="reviews")


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (UniqueConstraint("source", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(50))  # jira | trello | fixture
    external_id: Mapped[str] = mapped_column(String(100))
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("developers.id"), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    type: Mapped[str | None] = mapped_column(String(50), nullable=True)  # story | bug | task
    status: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # --- Katman 2: elle girilen, güvenilmez alanlar. Çoğu zaman BOŞ olacak. ---
    estimate_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    story_points: Mapped[float | None] = mapped_column(Float, nullable=True)

    transitions: Mapped[list["TaskStatusTransition"]] = relationship(back_populates="task")


class TaskStatusTransition(Base):
    """Katman 1: status geçişlerinin zaman damgaları. Kullanıcı tarih girmez,
    sistem status değişimini otomatik damgalar — cycle time buradan çıkar."""

    __tablename__ = "task_status_transitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"))
    from_status: Mapped[str | None] = mapped_column(String(100), nullable=True)
    to_status: Mapped[str] = mapped_column(String(100))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    task: Mapped[Task] = relationship(back_populates="transitions")


class CodeQualitySnapshot(Base):
    __tablename__ = "code_quality_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id"))
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    complexity: Mapped[float | None] = mapped_column(Float, nullable=True)
    duplication: Mapped[float | None] = mapped_column(Float, nullable=True)
    code_smells: Mapped[int | None] = mapped_column(Integer, nullable=True)


class MetricResult(Base):
    """Hesaplanmış metrik. data_completeness: bu değer hangi tamlık oranıyla
    üretildi — dashboard 'veri yetersiz' durumunu buradan dürüstçe gösterir."""

    __tablename__ = "metric_results"
    __table_args__ = (UniqueConstraint("scope", "scope_id", "metric_key", "period"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    scope: Mapped[str] = mapped_column(String(20))  # team | project | developer
    scope_id: Mapped[int] = mapped_column(Integer)
    metric_key: Mapped[str] = mapped_column(String(100))
    period: Mapped[str] = mapped_column(String(50))  # örn "2026-06-08/2026-07-07" ya da hafta anahtarı
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 0..1 — metriğin dayandığı kayıtların ne kadarında gerekli alanlar vardı
    data_completeness: Mapped[float] = mapped_column(Float, default=1.0)
    # Hangi katman/kaynaktan üretildi (git | jira_status | pr_merge ...)
    source_layer: Mapped[str | None] = mapped_column(String(50), nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Recommendation(Base):
    """Kural motorunun ürettiği insan-dostu öneriler (İlke D)."""

    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(primary_key=True)
    scope: Mapped[str] = mapped_column(String(20))
    scope_id: Mapped[int] = mapped_column(Integer)
    rule_key: Mapped[str] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(20), default="info")  # info | warning | attention
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
