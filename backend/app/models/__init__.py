"""Ortak normalize veri modeli (spec Bölüm 4).

Tüm kaynaklar (git, jira, trello, sonarqube) bu şemaya normalize edilir.
Kural: alanlar nullable'dır — eksik alan ilgili metriği devre dışı bırakır,
sistemi asla çökertmez (İlke A: kirli veri hata değil, ana özelliktir).
"""
from __future__ import annotations

from datetime import date, datetime

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
    # Baş yönetici (owner): role="admin" olan ama KORUNAN tek hesap. Tüm admin
    # yetkilerine sahiptir; ek olarak kimse onu silemez, rütbesini düşüremez,
    # pasifleştiremez ya da parolasını sıfırlayamaz. Sistemde en fazla bir tane.
    is_owner: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
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
    # İK alanları (HR düzenler; performans metriğine karışmaz):
    hire_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # işe giriş
    annual_allowance: Mapped[int] = mapped_column(
        Integer, default=14, server_default="14", nullable=False
    )  # yıllık izin hakkı (gün)
    # Login brute-force koruması (güvenlik): ardışık başarısız deneme sayacı +
    # geçici kilit. Başarılı girişte ikisi de sıfırlanır.
    failed_login_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Oturum geçersiz kılma: parola değişince artırılır; eski JWT'lerin 'tv'
    # claim'i eşleşmez → 401. Böylece parola değişimi eski token'ları düşürür.
    token_version: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
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
    # İnsanın commit mesajına yazabileceği kısa referans: Jira "PROJ-123",
    # Trello kart numarası "42". external_id'den AYRI tutulur çünkü Trello'da
    # external_id opak bir hash'tir. Dolu olduğunda task↔commit bağı tahmin
    # edilmez, konvansiyonla KESİNLEŞİR (bkz. services/task_link.py).
    task_key: Mapped[str | None] = mapped_column(String(50), nullable=True)
    task_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("developers.id"), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    type: Mapped[str | None] = mapped_column(String(50), nullable=True)  # story | bug | task
    status: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Kaynakta arşivlenmiş mi. Arşivli kart WIP'e sayılmaz (akışta değildir) ama
    # kaydı tutulur: arşivlenen kart çoğu zaman BİTMİŞ iştir ve onu hiç çekmemek
    # cycle time / teslim sinyalini kaybettiriyordu.
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Kaynakta EN SON ne zaman görüldü / ne zamandan beri KAYIP.
    # Ingest yalnız upsert yapıyordu: kaynaktan silinen kayıt DB'de sonsuza
    # kadar kalıyordu. Canlı ölçüm: board'da 21 kart varken DB'de 26 task vardı;
    # aradaki 5'i artık kullanılmayan bir board'dan kalmıştı ve her senkronda
    # "hiçbir takıma bağlı değil" uyarısı üretip metrik paydalarına giriyordu.
    # KALICI SİLME YOK: kayıt saklanır, yalnız hesaplardan çıkarılır — kaynak
    # geçici bir hata verdiyse veri kaybı yaşanmasın.
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    missing_since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
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


class TaskCommitLink(Base):
    """Task ↔ commit bağı: motorun ÖNERİSİ ya da insanın KARARI.

    Kaynaklarda bu bağ yoktur ve kurulamaz (bkz. services/task_link.py):
    Trello kart id'si commit mesajında geçmez, task'ların yalnız 2/26'sında
    assignee var. Bağ anlamsal benzerlikle TAHMİN edilir ve ölçüldüğünde
    isabet ~%50 çıktı — Türkçe kart başlığı ile İngilizce commit mesajını
    eşleştirmenin yapısal tavanı.

    Bu yüzden bağ iki aşamalı: motor önerir, insan onaylar. AI analizi
    YALNIZCA `confirmed` bağları kullanır. Tahmin üstüne analiz yazmak,
    sistemin yanlış commit'e bakıp kendinden emin konuşması demekti —
    RAG'daki 'zayıf bağlamla konuşma' kuralının aynısı burada da geçerli.

    `rejected` kaydı SİLİNMEZ: silinseydi motor her senkronda aynı yanlış
    commit'i yeniden önerir, insanın kararı her seferinde buharlaşırdı.
    """

    __tablename__ = "task_commit_links"
    __table_args__ = (UniqueConstraint("task_id", "commit_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"))
    commit_id: Mapped[int] = mapped_column(ForeignKey("commits.id"))
    # suggested = motor önerdi, kimse bakmadı | confirmed / rejected = insan kararı
    status: Mapped[str] = mapped_column(String(20), default="suggested")
    # Bağ NEREDEN geldi: 'semantic' = anlamsal benzerlik TAHMİNİ (onay ister),
    # 'convention' = commit mesajında kartın numarası yazıyor (tahmin yok).
    # İkisini ayırmadan saklamak, kullanıcının ekranda "%73 benzer" ile
    # "geliştirici [#42] yazmış" arasındaki farkı görememesi demekti.
    matched_by: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Öneri skoru saklanır: kullanıcı 'bu neden önerildi' diye sorabilmeli.
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    in_window: Mapped[bool] = mapped_column(Boolean, default=False)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# NOT: CodeQualitySnapshot (SonarQube/linter kalite anlık görüntüsü) KALDIRILDI —
# dış kod-kalitesi taraması artık yok, kod taraması AI modülüyle yapılır. Mevcut
# DB'lerdeki 'code_quality_snapshots' tablosu (varsa) orphan kalır, kullanılmaz.


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


class UserCredential(Base):
    """Kullanıcının KENDİ dış servis erişim anahtarı (şu an: GitHub PAT).

    Neden kullanıcı başına: sunucu geneli tek token, çalışanın özel reposuna
    erişmek için yöneticinin o repoya erişmesini gerektiriyordu — bir ürün için
    kabul edilemez. Ayrıca paylaşılan token, panele girebilen HERKESE token'ın
    ulaştığı tüm repoları açıyordu. Kendi anahtarıyla herkes yalnız kendi
    erişebildiğini görür.

    Değer at-rest şifrelenir (core.credential_crypto, Fernet). Düz metin
    hiçbir uçtan geri DÖNMEZ; yalnız `hint` (son 4 karakter) gösterilir.
    """

    __tablename__ = "user_credentials"
    __table_args__ = (UniqueConstraint("user_id", "provider"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    provider: Mapped[str] = mapped_column(String(50))  # github
    encrypted_value: Mapped[str] = mapped_column(Text)
    hint: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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
    # Yönetici kararının notu. Redde ZORUNLU (çalışana gerekçe); onayda opsiyonel.
    # Gizlilik: yalnız iznin sahibi ve yöneticiler görebilir.
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PayrollDocument(Base):
    """Bordro/özlük evrakı: çalışanın yüklediği belgenin KAYDI (dosya diskte).

    İÇERİK DB'DE DEĞİL: dosya `services/hr_documents.storage_root()` altında
    durur, burada yalnız meta + disk adı tutulur. Belgeler ölçekte megabaytlarca
    tarama/PDF; bunları satır içinde taşımak yedeklemeyi ve her sorguyu ağırlaştırır.

    ÖZEL NİTELİKLİ VERİ: istirahat raporu, engellilik raporu, icra müzekkeresi.
    Bu yüzden erişim dar (sahibi + admin/İK), her okuma denetim kaydına yazılır
    ve içerik hiçbir koşulda LLM katmanına verilmez.

    doc_type: services/hr_doc_types.DOC_TYPES kataloğunun anahtarı. Serbest metin
    DEĞİL — "kimin özlük dosyası eksik" ancak sabit anahtarla hesaplanabilir.

    period: belgenin ait olduğu bordro dönemi ("2026-08"). Rapor tarihi ile
    bordro dönemi AYNI ŞEY DEĞİLDİR (ay sonunda başlayan rapor bir sonraki
    bordroya sarkar), bu yüzden ayrı kolon.

    status: pending | approved | rejected — İK'nın belgeyi bordroya işlediğini
    (ya da neden işleyemediğini) çalışan görebilsin. Reddedilen kayıt SİLİNMEZ:
    gerekçe kaybolursa çalışan aynı eksik belgeyi tekrar yükler.
    """

    __tablename__ = "payroll_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Belge KİMİN hakkında (her zaman çalışanın kendisi).
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # Kim yükledi — çalışanın kendisi ya da onun adına İK. Hesap silinse de
    # belgenin kaydı kalsın diye SET NULL.
    uploaded_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    doc_type: Mapped[str] = mapped_column(String(40), index=True)
    period: Mapped[str | None] = mapped_column(String(7), nullable=True, index=True)  # YYYY-MM
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # İlgili izin kaydı (rapor ↔ izin). Bağ opsiyoneldir: belge izin talebinden
    # önce de gelebilir. İzin silinirse belge kaybolmasın diye SET NULL.
    leave_id: Mapped[int | None] = mapped_column(
        ForeignKey("leaves.id", ondelete="SET NULL"), nullable=True
    )
    # --- dosya meta ---
    original_name: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(80))  # uuid4hex + uzantı
    content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64))
    # --- İK kararı ---
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    reviewed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Redde ZORUNLU gerekçe (izin akışındaki decision_note ile aynı kural).
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    # Diff, modelin bağlam penceresine sığmadığı için kırpılarak gönderildi mi.
    # Panoda gösterilir: kırpılmış girdiye dayanan puan "tam analiz" sanılmamalı.
    truncated: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
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
    # Diff dışında kaç ek dosya okundu (derin okuma aracı). 0 = yalnız diff.
    extra_reads: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    provider: Mapped[str | None] = mapped_column(String(20), nullable=True)
    model: Mapped[str | None] = mapped_column(String(60), nullable=True)
    outcome: Mapped[str] = mapped_column(String(20))  # ok | error | skipped
    # Bağlam bütçesi için prompt kırpıldı mı (denetim: modele ne gitti).
    truncated: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SyncState(Base):
    """Kaynak bazında son BAŞARILI senkron zamanı (artımlı çekim için).

    NEDEN: adaptörlerin hepsi `fetch_*(since=...)` destekliyordu ama ingest
    hepsini PARAMETRESİZ çağırıyordu — kod tabanında `since` üreten tek satır
    yoktu. Sonuç: her saat tam çekim. GitHub'da repo başına ~350 istek/saat
    (10 sayfa commit + 150 commit detayı + 200 PR + review istekleri); 5000/saat
    sınırında ~13 repo tavanı, token'sız kurulumda ilk repoda biter.

    KRİTİK KURAL: damga yalnız UYARISIZ (eksiksiz) çekimden sonra ilerletilir.
    Kısmi başarıda ilerletmek, alınamayan veriyi kalıcı olarak atlamak olurdu.
    """

    __tablename__ = "sync_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_kind: Mapped[str] = mapped_column(String(20), unique=True)  # git | tasks
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


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


class SurveyCycle(Base):
    """Anket döngüsü (2 haftalık pencere). Cevaplar ve katılım buna bağlanır —
    ama birbirine DEĞİL. Kimlik yalnız katılımda, cevap kimliksizdir."""

    __tablename__ = "survey_cycles"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(40), unique=True)  # ör. "20260706-20260719"
    opens_at: Mapped[date] = mapped_column(Date)
    closes_at: Mapped[date] = mapped_column(Date)
    is_open: Mapped[bool] = mapped_column(Boolean, default=True)
    # Döngü açılırken o anki soru taslağının SNAPSHOT'ı (JSON list:
    # [{key,label,type,required}]). Sorular sonradan değişse bile bu döngünün
    # formu/agregası dondurulmuş sorulara göre çalışır. Eski döngülerde NULL →
    # config.survey.questions'a düşülür (geriye uyum).
    questions_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class SurveyResponse(Base):
    """Anonim anket cevabı. ANONİMLİK ÇEKİRDEĞİ: hiçbir kullanıcı/kişi kimliği
    YOK (user_id/developer_id yok), hassas zaman damgası YOK. Yalnız cycle_id +
    şifreli payload. Kim doldurdu bilgisi ayrı SurveyParticipation'da; iki tablo
    JOIN edilse bile cevap-kişi eşleşmesi çıkmaz (ortak/sıralı anahtar yok)."""

    __tablename__ = "survey_responses"

    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("survey_cycles.id"))
    # Save'den önce şifrelenmiş {answers, comment, schema_version} (Fernet).
    ciphertext: Mapped[str] = mapped_column(Text)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)


class SurveyQuestionTemplate(Base):
    """Admin'in düzenlediği anket soru TASLAĞI (tek kaynak, sıralı). Döngü
    açılırken bu taslak SurveyCycle.questions_json'a snapshot'lanır; taslak
    değişikliği yalnız BİR SONRAKİ döngüde geçerli olur (açık/geçmiş döngü
    dondurulmuş sorularını korur). Boşsa config.survey.questions'tan seed'lenir."""

    __tablename__ = "survey_question_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    key: Mapped[str] = mapped_column(String(32), unique=True)
    label: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(16), default="likert")  # likert | text
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class SurveyParticipation(Base):
    """"Bu döngüde doldurdu mu" defteri — CEVABI TUTMAZ. Döngü başına tek kayıt
    (tekrar doldurmayı engeller, hatırlatma/katılım oranı için). Zaman damgası
    KASITLI YOK: cevap satırının insert sırasıyla korelasyon kurulmasın."""

    __tablename__ = "survey_participations"
    __table_args__ = (UniqueConstraint("cycle_id", "user_id", name="uq_survey_participation"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("survey_cycles.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))


class DocChunk(Base):
    """RAG indeksinin birimi: normalize bir kaydın metinleşmiş hâli + vektörü.

    Kaynak DAİMA normalize şemadır (commits/pull_requests/tasks) — GitLab ya da
    Trello'ya doğrudan istek atılmaz. Böylece yeni bir kaynak adaptörü eklendiğinde
    RAG katmanı hiç değişmez.

    Metin KİŞİ ADI TAŞIMAZ (İlke E). Yazar/atanan bilgisi buraya hiç girmez;
    chunk "kim yaptı"yı değil "ne oldu"yu anlatır.

    content_hash: kayıt değişmediyse yeniden gömme (embedding çağrısı) yapılmaz.
    model: hangi embedding modeliyle gömüldüğü — model değişirse chunk yeniden gömülür,
    çünkü farklı modellerin vektörleri aynı uzayda DEĞİLDİR ve sessizce
    karşılaştırılırsa retrieval saçmalar.
    """

    __tablename__ = "doc_chunks"
    __table_args__ = (UniqueConstraint("source_kind", "source_id", "chunk_index"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_kind: Mapped[str] = mapped_column(String(20))  # commit | pr | task
    source_id: Mapped[int] = mapped_column(Integer)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    # Vektör JSON listesi olarak durur: hem PostgreSQL hem SQLite'ta taşınabilir.
    # pgvector kurulduğunda arama katmanı değişir, şema değişmez (bkz. rag/index.py).
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    embedded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class RagQueryAudit(Base):
    """RAG sorgusunda LLM'e NE gittiğinin denetim kaydı (gizlilik şeffaflığı).

    İçerik saklanmaz — yalnızca meta: kaç chunk, kaç karakter, kaç secret
    maskelendi, sonuç ne oldu. Soru metni de saklanmaz (hash'i saklanır):
    soru başlı başına kişisel veri taşıyabilir."""

    __tablename__ = "rag_query_audit"

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    question_hash: Mapped[str] = mapped_column(String(64))
    chunks_sent: Mapped[int] = mapped_column(Integer, default=0)
    chars_sent: Mapped[int] = mapped_column(Integer, default=0)
    masked_secrets: Mapped[int] = mapped_column(Integer, default=0)
    provider: Mapped[str | None] = mapped_column(String(20), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # ok | insufficient_context | disabled | error
    outcome: Mapped[str] = mapped_column(String(30))
    asked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PasswordResetCode(Base):
    """"Şifremi unuttum" akışının 6 haneli doğrulama kodu.

    SIR SAKLANMAZ: kodun kendisi değil yalnızca HASH'i tutulur (code_hash) —
    veritabanını okuyabilen biri kodu öğrenip hesabı ele geçiremesin. Aynı
    sebeple `reset_token_hash` de hash'lidir: kod doğrulandıktan sonra verilen
    tek kullanımlık jeton da bir sırdır.

    İKİ AŞAMALI: kod doğrulanınca (verify) kısa ömürlü bir reset jetonu üretilir
    ve son adımda (reset) kod tekrar sorulmaz. Böylece kullanıcı parolayı
    yazarken kodu elinde tutmak zorunda kalmaz.

    attempts: her hatalı denemede artar; eşiğe ulaşınca kod iptal edilir
    (used_at damgalanır) — kaba kuvvetle 6 hane denenmesin.
    """

    __tablename__ = "password_reset_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    code_hash: Mapped[str] = mapped_column(String(64))       # sha256 hexdigest
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    # Kod tüketildi/iptal edildi damgası. NULL = hâlâ kullanılabilir.
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Kod doğrulandıktan sonra verilen tek kullanımlık jeton (hash'li) + ömrü.
    reset_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reset_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
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
