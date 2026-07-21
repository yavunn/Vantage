"""Ortak normalize veri modeli (spec Bölüm 4).

Tüm kaynaklar (git, jira, trello, sonarqube) bu şemaya normalize edilir.
Kural: alanlar nullable'dır — eksik alan ilgili metriği devre dışı bırakır,
sistemi asla çökertmez (İlke A: kirli veri hata değil, ana özelliktir).
"""
from __future__ import annotations

from datetime import datetime

from datetime import date

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
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
    """Giriş hesabı. Mevcut `users` tablosuna eşlenir (email + bcrypt hash).

    Bir kullanıcı isteğe bağlı olarak bir Developer'a bağlıdır (developer_id):
    dashboard'daki kimlik/yetki katmanı bu bağ üzerinden çalışır. Saf admin
    hesapları (developer_id = NULL) da olabilir.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(200), nullable=True)
    role: Mapped[str] = mapped_column(String(20), default="user")  # user | admin
    developer_id: Mapped[int | None] = mapped_column(
        ForeignKey("developers.id"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Admin'in verdiği geçici parola: ilk girişte değiştirme zorunlu.
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    # Profil alanları (kullanıcı kendi düzenler) — hiçbiri metriğe karışmaz.
    title: Mapped[str | None] = mapped_column(String(120), nullable=True)  # ünvan/pozisyon
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(60), nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    developer: Mapped["Developer | None"] = relationship()


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
    # Değerin dayandığı kayıt sayısı — az örneklem yanıltıcı olmasın diye gösterilir
    sample_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Süre metriklerinde dağılım: {"median": .., "p90": .., "min": .., "max": ..}
    # Ortalama tek başına yanıltıcı; medyan/p90 yanına eklenir. Yoksa NULL.
    stats: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class UserProject(Base):
    """Kullanıcının kendi eklediği dış proje (örn. GitHub reposu).

    Bilinçli izolasyon: bu projenin commitleri ayrı `project_commits`
    tablosuna gider — takım metriklerini besleyen `commits` tablosuna
    KARIŞMAZ (kullanıcı reposu takım delivery metriğini kirletmesin)."""

    __tablename__ = "user_projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    project_name: Mapped[str] = mapped_column(String(200))
    source_type: Mapped[str | None] = mapped_column(String(50), nullable=True)  # github
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    repo_id: Mapped[int | None] = mapped_column(ForeignKey("repos.id"), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(20), nullable=True)  # ok | error
    last_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    commits: Mapped[list["ProjectCommit"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    reviews: Mapped[list["CommitReview"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class ProjectCommit(Base):
    """Dış projeden çekilen ham commit. Metrik motoruna girmez."""

    __tablename__ = "project_commits"
    __table_args__ = (UniqueConstraint("user_project_id", "sha"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_project_id: Mapped[int] = mapped_column(ForeignKey("user_projects.id"))
    sha: Mapped[str] = mapped_column(String(64))
    author_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    author_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    additions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deletions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    changed_files: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped[UserProject] = relationship(back_populates="commits")


class CommitReview(Base):
    """Bir projenin commit pratiği için üretilmiş değerlendirme (AI veya kural).
    Skor KİŞİYE değil commit PRATİĞİNE aittir (mesaj kalitesi, atomiklik, düzen)."""

    __tablename__ = "commit_reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_project_id: Mapped[int] = mapped_column(ForeignKey("user_projects.id"))
    commit_count: Mapped[int] = mapped_column(Integer, default=0)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0..100
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # boyut kırılımı
    provider: Mapped[str | None] = mapped_column(String(20), nullable=True)  # rule | local | claude
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped[UserProject] = relationship(back_populates="reviews")


class Leave(Base):
    """İzin kaydı. İK/kapasite bağlamıdır — performans metriğine KARIŞMAZ.

    Mevcut `leaves` tablosuna eşlenir (onay alanlarıyla)."""

    __tablename__ = "leaves"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    developer_id: Mapped[int | None] = mapped_column(ForeignKey("developers.id"), nullable=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    leave_type: Mapped[str] = mapped_column(String(20))  # annual | sick | other
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="approved")
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


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


class TrendAnnotation(Base):
    """Trend grafiklerine düşen işaret (tatil, incident, sürüm). Bir tepe/çukur
    yanlış okunmasın diye bağlam verir. team_id NULL = tüm takımlar (ör. resmi
    tatil). Metrik verisini DEĞİŞTİRMEZ; yalnızca görsel bağlamdır."""

    __tablename__ = "trend_annotations"

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    date: Mapped[date] = mapped_column(Date)
    label: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20), default="other")  # holiday | incident | release | other
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CodeAnalysis(Base):
    """AI kod analizi sonucu (repo/dosya düzeyi — KİŞİ DEĞİL). Her boyut 0-100.
    diff_hash: analiz edilen diff'in SHA256'sı — aynı diff tekrar analiz
    edilmesin (maliyet). Değer yoksa None: 'analiz bekliyor' gösterilir."""

    __tablename__ = "code_analyses"
    __table_args__ = (UniqueConstraint("repo_id", "diff_hash", name="uq_code_analysis"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_id: Mapped[int | None] = mapped_column(ForeignKey("repos.id"), nullable=True)
    # Kod git commit YAZARINA atfedilir (kişi-bazlı analiz). NULL = atfedilmemiş.
    developer_id: Mapped[int | None] = mapped_column(ForeignKey("developers.id"), nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    file_path: Mapped[str] = mapped_column(Text)
    diff_hash: Mapped[str] = mapped_column(String(64))
    diff_lines: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 7 boyut (0-100). None = üretilemedi.
    readability: Mapped[int | None] = mapped_column(Integer, nullable=True)
    complexity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    maintainability: Mapped[int | None] = mapped_column(Integer, nullable=True)
    test_adequacy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    security: Mapped[int | None] = mapped_column(Integer, nullable=True)
    code_smells: Mapped[int | None] = mapped_column(Integer, nullable=True)
    conventions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    composite: Mapped[float | None] = mapped_column(Float, nullable=True)
    suggestions: Mapped[list | None] = mapped_column(JSON, nullable=True)  # [{"text":...}]
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(20), nullable=True)  # claude | local
    model: Mapped[str | None] = mapped_column(String(60), nullable=True)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CodeAnalysisAudit(Base):
    """LLM'e HANGİ verinin gittiğinin denetim kaydı (İlke: gizlilik/denetlenebilir).
    İçerik saklanmaz — yalnızca meta: dosya, hash, boyut, maskelenen secret sayısı."""

    __tablename__ = "code_analysis_audit"

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_id: Mapped[int | None] = mapped_column(ForeignKey("repos.id"), nullable=True)
    file_path: Mapped[str] = mapped_column(Text)
    diff_hash: Mapped[str] = mapped_column(String(64))
    chars_sent: Mapped[int] = mapped_column(Integer)
    masked_secrets: Mapped[int] = mapped_column(Integer, default=0)
    provider: Mapped[str | None] = mapped_column(String(20), nullable=True)
    model: Mapped[str | None] = mapped_column(String(60), nullable=True)
    outcome: Mapped[str] = mapped_column(String(20))  # ok | error | skipped
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    """Yönetici işlemlerinin denetim kaydı (hesap verebilirlik).
    KİM neyi KİME yaptı: parola sıfırlama, rol/durum değişimi, ekleme, silme.
    Hassas içerik (parola vb.) ASLA saklanmaz — yalnızca eylem + hedef + meta."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    action: Mapped[str] = mapped_column(String(40))  # create_employee | delete_employee | ...
    target_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {"role":"user->admin"}
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Notification(Base):
    """Kullanıcıya gösterilecek bildirim (trend alarmı, sistem olayı).
    Etik: bildirim de gözetim aracı değil — takım sağlığı sinyali ("kırmızıya
    döndü, yardım gerekebilir"), kişi kıyası ya da ceza dili İÇERMEZ."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(40))  # trend_alarm | system | info
    severity: Mapped[str] = mapped_column(String(10), default="info")  # info | warning | critical
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Aynı olayın tekrar tekrar bildirilmemesi için tekilleştirme anahtarı.
    dedup_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    link: Mapped[str | None] = mapped_column(String(300), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
