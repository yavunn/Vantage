"""Ingest servisi: normalize DTO'ları DB'ye idempotent şekilde yazar.

Kirli veri stratejisi tek yerdedir:
- Kimliği belirsiz yazar/atanan → developer kaydı açılmaz, alan None kalır.
- Tekrarlanan kayıt (aynı sha / external_id) → güncellenir, çoğaltılmaz.
- Eksik tarih/alan → olduğu gibi None yazılır; karar metrik motorunundur.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.base import (
    GitProvider,
    NormalizedCommit,
    NormalizedPR,
    NormalizedTask,
    NormalizedTeamMember,
    TaskProvider,
)
from app.models import (
    Commit,
    Developer,
    PRReview,
    PullRequest,
    Repo,
    Task,
    TaskStatusTransition,
    Team,
    TeamMembership,
)


class Ingestor:
    def __init__(self, session: Session, repo_team_map: dict[str, str] | None = None):
        self.session = session
        self._repo_cache: dict[str, Repo] = {}
        self._dev_cache: dict[str, Developer] = {}
        self._team_cache: dict[str, Team] = {}
        self._repo_team_map: dict[str, str] = repo_team_map or {}

    # --- yardımcı çözümleyiciler ---------------------------------------------

    def _repo(self, name: str, team_name: str | None = None) -> Repo:
        if name in self._repo_cache:
            return self._repo_cache[name]
        # Commit/PR/kalite normalize kaydı takım taşımaz; config'teki repo→takım
        # eşlemesinden çözülür (git_log/gitlab/sonarqube gerçek kaynaklarında
        # takım panosunun dolması için gerekli).
        team_name = team_name or self._repo_team_map.get(name)
        repo = self.session.scalar(select(Repo).where(Repo.name == name))
        if repo is None:
            repo = Repo(name=name, team_id=self._team(team_name).id if team_name else None)
            self.session.add(repo)
            self.session.flush()
        elif team_name:
            # Config eşlemesi kaynaktır: takımsız kalmışı bağlar, YANLIŞ bağlanmışı
            # düzeltir. (Yönetici panelinden takım değiştirilebildiği için bu şart —
            # yalnız None'ı doldurmak, yeniden atamayı sessizce yutardı.)
            target = self._team(team_name)
            if repo.team_id != target.id:
                repo.team_id = target.id
                self.session.flush()
        self._repo_cache[name] = repo
        return repo

    def _team(self, name: str) -> Team:
        if name in self._team_cache:
            return self._team_cache[name]
        team = self.session.scalar(select(Team).where(Team.name == name))
        if team is None:
            team = Team(name=name)
            self.session.add(team)
            self.session.flush()
        self._team_cache[name] = team
        return team

    def _developer(self, source: str, key: str | None, name: str | None) -> Developer | None:
        """Kaynak-içi kimlikten developer çözer. Kimlik yoksa None döner —
        sahte 'unknown' geliştirici üretilmez, o kayıt kişiye bağlanmaz."""
        if not key:
            return None
        cache_key = f"{source}:{key}"
        if cache_key in self._dev_cache:
            return self._dev_cache[cache_key]
        # JSON external_ids içinde arama: az geliştirici olduğundan tam tarama makul
        for dev in self.session.scalars(select(Developer)):
            if dev.external_ids.get(source) == key:
                self._dev_cache[cache_key] = dev
                return dev
        dev = Developer(external_ids={source: key}, display_name=name or key)
        self.session.add(dev)
        self.session.flush()
        self._dev_cache[cache_key] = dev
        return dev

    # --- ingest girişleri ------------------------------------------------------

    def ingest_commits(self, commits: list[NormalizedCommit]) -> int:
        count = 0
        for c in commits:
            if not c.sha:
                continue  # kimliksiz kayıt atlanır, senkron sürer
            repo = self._repo(c.repo_name)
            row = self.session.scalar(
                select(Commit).where(Commit.repo_id == repo.id, Commit.sha == c.sha)
            )
            if row is None:
                row = Commit(repo_id=repo.id, sha=c.sha)
                self.session.add(row)
                count += 1
            author = self._developer("git", c.author_key, c.author_name)
            row.author_id = author.id if author else None
            row.committed_at = c.committed_at
            row.message = c.message
            row.changed_files = c.changed_files
            row.additions = c.additions
            row.deletions = c.deletions
        self.session.flush()
        return count

    def ingest_pull_requests(self, prs: list[NormalizedPR]) -> int:
        count = 0
        for p in prs:
            repo = self._repo(p.repo_name)
            row = self.session.scalar(
                select(PullRequest).where(
                    PullRequest.repo_id == repo.id, PullRequest.external_id == p.external_id
                )
            )
            if row is None:
                row = PullRequest(repo_id=repo.id, external_id=p.external_id)
                self.session.add(row)
                self.session.flush()
                count += 1
            author = self._developer("git", p.author_key, p.author_name)
            row.author_id = author.id if author else None
            row.title = p.title
            row.opened_at = p.opened_at
            row.first_review_at = p.first_review_at
            row.merged_at = p.merged_at
            row.closed_at = p.closed_at
            # Review'lar yeniden yazılır (kaynak gerçeği esastır)
            for old in list(row.reviews):
                self.session.delete(old)
            self.session.flush()
            for r in p.reviews:
                reviewer = self._developer("git", r.reviewer_key, None)
                self.session.add(
                    PRReview(
                        pr_id=row.id,
                        reviewer_id=reviewer.id if reviewer else None,
                        reviewed_at=r.reviewed_at,
                    )
                )
        self.session.flush()
        return count

    def ingest_team_members(self, members: list[NormalizedTeamMember]) -> int:
        """Kaynaktaki kadroyu takım üyeliğine yazar — YALNIZCA EKLER.

        Repo→takım eşlemesinin aksine burada 'kaynak haklıdır' demiyoruz: board
        üyeliği ile ölçüm kadrosu aynı şey değildir (izleyici, stajyer, eski üye
        board'da durur). Kaynakta olmayan üyeliği silmek, panelden yapılmış
        bilinçli bir atamayı sessizce geri alırdı — o yüzden silme yok, çıkarma
        panelden yapılır.
        """
        count = 0
        for m in members:
            if not m.team_name or not m.member_key:
                continue
            team = self._team(m.team_name)
            dev = self._developer(m.source, m.member_key, m.member_name)
            if dev is None:
                continue
            exists = self.session.scalar(
                select(TeamMembership).where(
                    TeamMembership.team_id == team.id,
                    TeamMembership.developer_id == dev.id,
                )
            )
            if exists is None:
                self.session.add(
                    TeamMembership(team_id=team.id, developer_id=dev.id, role="member")
                )
                count += 1
        self.session.flush()
        return count

    def ingest_tasks(self, tasks: list[NormalizedTask]) -> int:
        count = 0
        for t in tasks:
            row = self.session.scalar(
                select(Task).where(Task.source == t.source, Task.external_id == t.external_id)
            )
            if row is None:
                row = Task(source=t.source, external_id=t.external_id)
                self.session.add(row)
                self.session.flush()
                count += 1
            assignee = self._developer(t.source, t.assignee_key, t.assignee_name)
            row.team_id = self._team(t.team_name).id if t.team_name else None
            row.assignee_id = assignee.id if assignee else None
            row.title = t.title
            row.type = t.type
            row.status = t.status
            row.created_at = t.created_at
            row.estimate_hours = t.estimate_hours
            row.due_date = t.due_date
            row.story_points = t.story_points
            for old in list(row.transitions):
                self.session.delete(old)
            self.session.flush()
            for tr in t.transitions:
                self.session.add(
                    TaskStatusTransition(
                        task_id=row.id,
                        from_status=tr.from_status,
                        to_status=tr.to_status,
                        changed_at=tr.changed_at,
                    )
                )
        self.session.flush()
        return count


def run_ingest(
    session: Session,
    git: GitProvider | None,
    tasks: TaskProvider | None,
    repo_team_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Tüm kaynaklardan çek + normalize et + yaz. Kaynak yoksa atlanır.
    repo_team_map: repo adı → takım adı (config'ten; commit/PR kaynağı takım
    taşımadığında panonun dolması için).

    Sayılar YENİ kayıt sayısıdır (idempotent: var olan güncellenir, sayılmaz).
    'warnings' adaptörlerin okuyamadığı kaynakları taşır — sessiz başarısızlık
    yerine çağıran bunu kullanıcıya gösterir."""
    ing = Ingestor(session, repo_team_map=repo_team_map)
    stats: dict[str, Any] = {"commits": 0, "pull_requests": 0, "tasks": 0, "team_members": 0}
    warnings: list[str] = []
    if git is not None:
        stats["commits"] = ing.ingest_commits(git.fetch_commits())
        stats["pull_requests"] = ing.ingest_pull_requests(git.fetch_pull_requests())
        warnings.extend(getattr(git, "warnings", []))
    if tasks is not None:
        # Kadro ÖNCE: board üye listesi görünen adı taşır, kart ataması taşımaz.
        # Bu sırayla kişi "Ayşe Yılmaz" olarak açılır, ham kaynak id'siyle değil.
        # Uyarılar her çağrıdan sonra toplanır — adaptör her fetch'te sıfırlar.
        members = tasks.fetch_team_members() if hasattr(tasks, "fetch_team_members") else []
        stats["team_members"] = ing.ingest_team_members(members)
        warnings.extend(getattr(tasks, "warnings", []))
        stats["tasks"] = ing.ingest_tasks(tasks.fetch_tasks())
        warnings.extend(getattr(tasks, "warnings", []))
        warnings.extend(_unlinked_identity_warnings(session))
    session.commit()
    # Aynı uyarı iki kez toplanabilir (kadro ve görev çekimi aynı board'a bakar);
    # tekrarı göstermek gürültü, sırayı bozmak bilgi kaybı — sırayı koruyup tekille.
    stats["warnings"] = list(dict.fromkeys(warnings))
    return stats


def _unlinked_identity_warnings(session: Session) -> list[str]:
    """Görev kaynağından gelen ama git kimliği bağlanmamış kişileri bildirir.

    Aynı insan git'te e-postasıyla, Trello'da üye id'siyle görünür; ingest bunları
    eşleştiremez (farklı kaynak, farklı anahtar) ve İKİ ayrı kişi kaydı açar. Bu
    sessiz kalırsa takım kadrosu şişer ve WIP paydası bölündüğü için metrik
    olduğundan İYİ görünür. Eşleme Entegrasyon panelinden yapılır.
    """
    unlinked = [
        dev.display_name
        for dev in session.scalars(select(Developer))
        if (ids := dev.external_ids or {}) and not ids.get("git") and (ids.keys() - {"git"})
    ]
    if not unlinked:
        return []
    return [
        f"{len(unlinked)} kişinin git kimliği bağlı değil ({', '.join(sorted(unlinked)[:5])}"
        f"{'…' if len(unlinked) > 5 else ''}) — aynı kişi commit'lerde ayrı sayılıyor olabilir. "
        "Entegrasyon → Kimlik eşleme bölümünden bağlayın."
    ]
