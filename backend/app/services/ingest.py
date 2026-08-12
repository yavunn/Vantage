"""Ingest servisi: normalize DTO'ları DB'ye idempotent şekilde yazar.

Kirli veri stratejisi tek yerdedir:
- Kimliği belirsiz yazar/atanan → developer kaydı açılmaz, alan None kalır.
- Tekrarlanan kayıt (aynı sha / external_id) → güncellenir, çoğaltılmaz.
- Eksik tarih/alan → olduğu gibi None yazılır; karar metrik motorunundur.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.base import (
    GitProvider,
    NormalizedAssignee,
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
    TaskAssignee,
    TaskStatusTransition,
    Team,
    TeamMembership,
)
from app.services.identity import GIT_SOURCE, git_emails


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
        # git kimliği bir e-posta KÜMESİdir (aynı insan kişisel adresi + GitHub
        # noreply adresiyle commit atar), diğer kaynaklarda tek anahtar.
        aranan = key.strip().lower() if source == GIT_SOURCE else key
        # JSON external_ids içinde arama: az geliştirici olduğundan tam tarama makul
        for dev in self.session.scalars(select(Developer)):
            if source == GIT_SOURCE:
                eslesti = aranan in git_emails(dev.external_ids)
            else:
                eslesti = (dev.external_ids or {}).get(source) == key
            if eslesti:
                self._dev_cache[cache_key] = dev
                return dev
        dev = Developer(external_ids={source: aranan}, display_name=name or key)
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

    def _write_assignees(self, row: Task, t: NormalizedTask) -> None:
        """Kartın TÜM atananlarını yazar (kaynak gerçeği esastır: yeniden yazılır).

        `assignees` boşsa tek atananlı kaynaktır (Jira, fixture) ve
        `assignee_key`'e düşülür — böylece "kartın atananları" sorusu her
        kaynakta aynı yerden cevaplanır, çağıran taraf kaynağı bilmek zorunda
        kalmaz.
        """
        girdiler = list(t.assignees)
        if not girdiler and t.assignee_key:
            girdiler = [NormalizedAssignee(key=t.assignee_key, name=t.assignee_name)]

        for old in list(row.assignees):
            self.session.delete(old)
        self.session.flush()

        yazilan: set[int] = set()
        for sira, a in enumerate(girdiler):
            dev = self._developer(t.source, a.key, a.name)
            if dev is None or dev.id in yazilan:
                continue  # aynı üye iki kez listelenmişse tek satır
            yazilan.add(dev.id)
            self.session.add(
                TaskAssignee(task_id=row.id, developer_id=dev.id, is_primary=(sira == 0))
            )

    def ingest_tasks(self, tasks: list[NormalizedTask]) -> int:
        count = 0
        now = datetime.now(timezone.utc)
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
            row.task_key = t.key
            row.task_url = t.url
            row.team_id = self._team(t.team_name).id if t.team_name else None
            row.assignee_id = assignee.id if assignee else None
            row.title = t.title
            row.type = t.type
            row.status = t.status
            row.archived = bool(t.archived)
            # Kaynakta görüldü: kaybolma damgası varsa temizlenir (kayıt geri geldi).
            row.last_seen_at = now
            row.missing_since = None
            row.created_at = t.created_at
            row.estimate_hours = t.estimate_hours
            row.due_date = t.due_date
            row.story_points = t.story_points
            self._write_assignees(row, t)
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

    def mark_missing_tasks(self, sources: set[str], gorulen_ids: set[tuple[str, str]]) -> int:
        """Bu senkronda kaynakta GÖRÜLMEYEN task'ları 'kayıp' damgalar.

        YALNIZCA çekimi eksiksiz olan kaynaklar için çağrılmalıdır: kaynak hata
        verdiyse ya da oran sınırına takıldıysa gelmeyen kayıt "silinmiş" değil
        "okunamamış"tır ve damgalamak gerçek veri kaybı olurdu.

        Kalıcı silme yapılmaz — kayıt saklanır, yalnız metrik ve indeksten çıkar.
        """
        if not sources:
            return 0
        now = datetime.now(timezone.utc)
        sayi = 0
        for row in self.session.scalars(select(Task).where(Task.source.in_(sources))):
            if (row.source, row.external_id) in gorulen_ids:
                continue
            if row.missing_since is None:
                row.missing_since = now
                sayi += 1
        self.session.flush()
        return sayi


def _sync_state(session: Session, kind: str):
    from app.models import SyncState

    row = session.scalar(select(SyncState).where(SyncState.source_kind == kind))
    if row is None:
        row = SyncState(source_kind=kind)
        session.add(row)
        session.flush()
    return row


def run_ingest(
    session: Session,
    git: GitProvider | None,
    tasks: TaskProvider | None,
    repo_team_map: dict[str, str] | None = None,
    incremental: bool = True,
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
    now = datetime.now(timezone.utc)
    if git is not None:
        # Artımlı çekim YALNIZ git tarafında: asıl maliyet orada (GitHub'da
        # repo başına ~350 istek/saat). Görev kaynakları bilinçle TAM çekilir —
        # Trello `since`'i zaten yok sayar ve tam görüntü olmadan "kaynakta yok"
        # tespiti (mark_missing_tasks) yanlış kayıtları kayıp sayardı.
        git_state = _sync_state(session, "git")
        since_git = git_state.last_success_at if incremental else None
        stats["git_since"] = since_git.isoformat() if since_git else None
        stats["commits"] = ing.ingest_commits(git.fetch_commits(since_git))
        stats["pull_requests"] = ing.ingest_pull_requests(git.fetch_pull_requests(since_git))
        git_warnings = list(getattr(git, "warnings", []))
        # Damga yalnız EKSİKSİZ çekimden sonra ilerler: kısmi başarıda
        # ilerletmek, alınamayan commit'leri kalıcı olarak atlamak demektir.
        if not git_warnings:
            git_state.last_success_at = now
            git_state.updated_at = now
        warnings.extend(git_warnings)
    if tasks is not None:
        # Kadro ÖNCE: board üye listesi görünen adı taşır, kart ataması taşımaz.
        # Bu sırayla kişi "Ayşe Yılmaz" olarak açılır, ham kaynak id'siyle değil.
        # Uyarılar her çağrıdan sonra toplanır — adaptör her fetch'te sıfırlar.
        members = tasks.fetch_team_members() if hasattr(tasks, "fetch_team_members") else []
        stats["team_members"] = ing.ingest_team_members(members)
        warnings.extend(getattr(tasks, "warnings", []))
        cekilen = tasks.fetch_tasks()
        # Çekim uyarısızsa EKSİKSİZ sayılır; ancak o zaman "kaynakta yok"
        # damgası vurulabilir. Hatalı/kısmi çekimde damgalamak, okunamayan
        # kaydı silinmiş sanmak olurdu — gerçek veri kaybı.
        cekim_uyarilari = list(getattr(tasks, "warnings", []))
        stats["tasks"] = ing.ingest_tasks(cekilen)
        if not cekim_uyarilari:
            kayip = ing.mark_missing_tasks(
                {t.source for t in cekilen if t.source},
                {(t.source, t.external_id) for t in cekilen},
            )
            stats["tasks_missing"] = kayip
            if kayip:
                warnings.append(
                    f"{kayip} kayıt kaynakta bulunamadı (silinmiş ya da artık "
                    "çekilmeyen bir board'dan) — metriklerden ve asistan indeksinden "
                    "çıkarıldı. Kayıtlar silinmedi, yalnız hesaplardan düşürüldü."
                )
        warnings.extend(cekim_uyarilari)
        warnings.extend(_unlinked_identity_warnings(session))
        warnings.extend(_duplicate_identity_warnings(session))
    session.commit()
    # Aynı uyarı iki kez toplanabilir (kadro ve görev çekimi aynı board'a bakar);
    # tekrarı göstermek gürültü, sırayı bozmak bilgi kaybı — sırayı koruyup tekille.
    stats["warnings"] = list(dict.fromkeys(warnings))
    return stats


def _github_noreply_yerel(eposta: str) -> str | None:
    """'12345+kullanici@users.noreply.github.com' → 'kullanici'.

    GitHub'ın gizlilik e-postası gerçek kurulumlarda çok yaygın: aynı insan bir
    commit'te kişisel e-postasıyla, diğerinde bu adresle görünür ve ingest iki
    AYRI geliştirici kaydı açar."""
    e = (eposta or "").strip().lower()
    if not e.endswith("@users.noreply.github.com"):
        return None
    yerel = e.split("@", 1)[0]
    return yerel.split("+", 1)[1] if "+" in yerel else yerel


def duplicate_identity_pairs(session: Session) -> list[tuple[Developer, Developer, str]]:
    """Aynı kişi olma ihtimali yüksek geliştirici çiftleri + gerekçesi.

    OTOMATİK BİRLEŞTİRME YOK — kimlik kararı insanındır. Burada yalnız aday
    üretilir; onay Entegrasyon panelindeki birleştirme akışından geçer.

    Etik sınır: bu bir gözetim özelliği değil, VERİ KALİTESİ uyarısıdır. Kişi
    kıyası üreten hiçbir çıktı vermez.
    """
    devs = list(session.scalars(select(Developer)))
    adaylar: list[tuple[Developer, Developer, str]] = []
    for i, a in enumerate(devs):
        for b in devs[i + 1:]:
            # Kişi başına e-posta KÜMESİ: aynı insanın birden çok git adresi
            # tek kayıtta durabilir, karşılaştırma her ikili için yapılır.
            a_gitler, b_gitler = git_emails(a.external_ids), git_emails(b.external_ids)
            if not a_gitler or not b_gitler or set(a_gitler) & set(b_gitler):
                continue
            # 1) GitHub noreply ↔ kişisel e-posta: kullanıcı adı, diğerinin
            #    e-posta yerel kısmıyla ya da görünen adıyla eşleşiyor mu?
            noreply_eslesme = None
            for kaynak, oteki_gitler, oteki_ad in ((a_gitler, b_gitler, b.display_name),
                                                   (b_gitler, a_gitler, a.display_name)):
                for kul in filter(None, (_github_noreply_yerel(e) for e in kaynak)):
                    ad = (oteki_ad or "").strip().lower().replace(" ", "")
                    for oteki_git in oteki_gitler:
                        yerel = oteki_git.split("@", 1)[0].lower()
                        if kul == yerel or (ad and kul == ad):
                            noreply_eslesme = kul
                            break
                    if noreply_eslesme:
                        break
                if noreply_eslesme:
                    break
            if noreply_eslesme:
                adaylar.append(
                    (a, b, f"GitHub noreply e-postası '{noreply_eslesme}' ile eşleşiyor")
                )
            else:
                # 2) Aynı görünen ad + farklı git kimliği.
                ad_a = (a.display_name or "").strip().lower()
                ad_b = (b.display_name or "").strip().lower()
                if ad_a and ad_a == ad_b:
                    adaylar.append((a, b, "görünen ad aynı"))
                    continue
                # 3) Kaynak-dışı bir anahtar aynı (ör. aynı Trello üye id'si).
                ortak = {
                    k for k in (a.external_ids or {})
                    if k != "git" and (a.external_ids or {}).get(k)
                    and (a.external_ids or {}).get(k) == (b.external_ids or {}).get(k)
                }
                if ortak:
                    adaylar.append((a, b, f"aynı {', '.join(sorted(ortak))} kimliği"))
    return adaylar


def _duplicate_identity_warnings(session: Session) -> list[str]:
    adaylar = duplicate_identity_pairs(session)
    if not adaylar:
        return []
    ornekler = "; ".join(
        f"{a.display_name} ↔ {b.display_name} ({sebep})" for a, b, sebep in adaylar[:3]
    )
    return [
        f"{len(adaylar)} kişi çifti aynı insan olabilir ({ornekler}"
        f"{'…' if len(adaylar) > 3 else ''}) — takım üye sayısı şişer ve kişi başı "
        "metrikler (WIP) olduğundan İYİ görünür. Entegrasyon → Kimlik eşleme "
        "bölümünden birleştirin (otomatik birleştirme yapılmaz)."
    ]


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
        if (ids := dev.external_ids or {}) and not git_emails(ids) and (ids.keys() - {GIT_SOURCE})
    ]
    if not unlinked:
        return []
    return [
        f"{len(unlinked)} kişinin git kimliği bağlı değil ({', '.join(sorted(unlinked)[:5])}"
        f"{'…' if len(unlinked) > 5 else ''}) — aynı kişi commit'lerde ayrı sayılıyor olabilir. "
        "Entegrasyon → Kimlik eşleme bölümünden bağlayın."
    ]
