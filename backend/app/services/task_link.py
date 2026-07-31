"""Task ↔ commit eşleştirme.

Kaynaklarda bu bağ YOKTUR ve kurulamaz: Trello kart id'si opak bir hash
(`6a61c628...`), commit mesajında asla geçmez; Jira'daki `PROJ-123` konvansiyonu
da bu kurulumda kullanılmıyor. Kişi sinyali de yok — 26 task'ın yalnız 2'sinde
assignee dolu. Geriye iki sinyal kalıyor:

1. ANLAMSAL BENZERLİK (birincil). Task BAŞLIĞI ile commit MESAJI karşılaştırılır.

   RAG'ın `doc_chunks` vektörleri bu iş için KULLANILMAZ, ölçüldü: task chunk'ı
   "· Statü: DONE · Akış: … · İlk hareketten son harekete 4 gün" kalıbını taşır
   ve bu kalıp her task'ta aynı olduğu için vektörü domine eder — tüm task'lar
   birbirine ve `docs:`/`chore:` gibi genel dilli commit'lere benzer çıkar.
   6 örnekte ilk sıra isabeti: chunk ile 1/6, başlık ile 3/6. Bu yüzden
   başlıklar ayrıca gömülür (26+44 kayıt, saniyeler sürer).

2. ZAMAN (ikincil, YUMUŞAK). Sert filtre OLARAK KULLANILMAZ: bu kurulumda
   kartlar işin bir kısmı yazıldıktan sonra açılmış. Ölçüldü — "Yetki Bazlı
   sayfa kısıtlama" (23-27 Tem) ile ilgili commit 29 Tem'de, "Anotasyonlar
   taşınsın" (28-29 Tem) ile ilgili commit 24 Tem'de. Sert pencere bu doğru
   eşleşmeleri sessizce keserdi. Zaman yalnızca yakınlık PRİMİ verir.

Eşleştirme kesin değil TAHMİNdir; bu yüzden her bağ skorunu ve zaman
uyumunu taşır, çağıran taraf bunu kullanıcıya gösterebilsin.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Config
from app.models import Commit, Task, TaskCommitLink
from app.services.rag.embedding import cosine

DECIDED = ("confirmed", "rejected")

# Zaman primi: commit, task'ın hareket penceresine bu kadar gün yakınsa
# "zamanlama uyuyor" sayılır. Geniş tutuldu — bkz. modül başlığı.
WINDOW_MARGIN_DAYS = 7
# Yakınlık primi. Küçük tutuldu: zaman DESTEKLEYİCİ sinyal, karar verici değil.
# Büyütmek, aynı hafta yazılmış alakasız commit'i öne taşır.
TIME_BONUS = 0.03


@dataclass(frozen=True)
class CommitLink:
    commit_id: int
    sha: str
    message: str
    committed_at: datetime | None
    score: float          # anlamsal benzerlik (zaman primi HARİÇ)
    in_window: bool       # commit, task'ın hareket penceresine yakın mı
    rank_score: float     # sıralamada kullanılan bileşik skor


@dataclass
class TaskLinks:
    task_id: int
    title: str
    status: str | None
    window_start: datetime | None
    window_end: datetime | None
    span_days: int | None
    links: list[CommitLink]


def task_window(task: Task) -> tuple[datetime | None, datetime | None]:
    """Task'ın hareket penceresi: ilk geçişten son geçişe.

    Geçiş yoksa created_at'e düşer — kartın hiç hareket etmemesi de bilgidir
    (backlog'da bekliyor), uydurma pencere üretmeyiz."""
    transitions = sorted(task.transitions, key=lambda t: t.changed_at)
    if transitions:
        return transitions[0].changed_at, transitions[-1].changed_at
    return task.created_at, task.created_at


# Tek istekte gönderilecek metin sayısı. Yerel bir CPU modelinde (bge-m3)
# 44 metni tek seferde gömmek embedding ucunun 60 sn'lik zaman aşımını
# aşabiliyor — ölçüldü, ReadTimeout alındı. indexer.py ile aynı parti boyutu.
EMBED_BATCH = 32


def as_utc(dt: datetime | None) -> datetime | None:
    """Naive datetime'ı UTC kabul eder.

    Şart: `DateTime(timezone=True)` kolonları PostgreSQL'de tz-aware,
    SQLite'ta NAIVE döner. Karşılaştırmadan önce sabitlenmezse aynı kod
    Postgres'te çalışıp SQLite'ta (testler, demo kurulumu) TypeError verir.
    """
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _embed_batched(provider, texts: list[str]) -> list[list[float]]:
    out: list[list[float]] = []
    for start in range(0, len(texts), EMBED_BATCH):
        out.extend(provider.embed(texts[start:start + EMBED_BATCH]))
    return out


def _head(message: str | None) -> str:
    """Commit mesajının ilk satırı. Gövde bilerek atılır: uzun açıklama
    (ve co-author/footer satırları) kısa task başlığıyla kıyaslandığında
    vektörü sulandırır."""
    if not message:
        return ""
    return message.strip().splitlines()[0].strip()


def link_tasks(session: Session, cfg: Config, *, team_id: int | None = None,
               min_score: float | None = None, top_n: int = 5,
               provider=None) -> list[TaskLinks]:
    """Her task için en olası commit'leri döner.

    Eşik verilmezse RAG'ın `retrieval.min_score` değeri kullanılır — aynı
    embedding modeliyle ölçülmüş aynı ölçek, ikinci bir sihirli sayı üretmeyiz.
    """
    threshold = cfg.rag.retrieval.min_score if min_score is None else min_score

    if provider is None:
        from app.services.rag.embedding import build_embedding_provider
        provider = build_embedding_provider(cfg)
    if provider is None:
        return []

    stmt = select(Task)
    if team_id is not None:
        stmt = stmt.where(Task.team_id == team_id)
    tasks = [t for t in session.scalars(stmt) if (t.title or "").strip()]
    commits = [c for c in session.scalars(select(Commit)) if _head(c.message)]
    if not tasks or not commits:
        return []

    task_vec_list = _embed_batched(provider, [(t.title or "").strip() for t in tasks])
    commit_vec_list = _embed_batched(provider, [_head(c.message) for c in commits])
    commit_vecs = {c.id: v for c, v in zip(commits, commit_vec_list, strict=True)}
    commit_by_id = {c.id: c for c in commits}

    results: list[TaskLinks] = []
    for task, tvec in zip(tasks, task_vec_list, strict=True):
        start, end = task_window(task)
        lo = (as_utc(start) - timedelta(days=WINDOW_MARGIN_DAYS)) if start else None
        hi = (as_utc(end) + timedelta(days=WINDOW_MARGIN_DAYS)) if end else None

        links: list[CommitLink] = []
        for commit_id, cvec in commit_vecs.items():
            score = cosine(tvec, cvec)
            if score < threshold:
                continue
            commit = commit_by_id[commit_id]
            at = commit.committed_at
            at_utc = as_utc(at)
            in_window = bool(at_utc and lo and hi and lo <= at_utc <= hi)
            links.append(CommitLink(
                commit_id=commit_id, sha=commit.sha,
                message=_head(commit.message)[:120],
                committed_at=at, score=round(score, 4), in_window=in_window,
                rank_score=round(score + (TIME_BONUS if in_window else 0.0), 4),
            ))

        links.sort(key=lambda x: x.rank_score, reverse=True)
        span = (end - start).days if (start and end) else None
        results.append(TaskLinks(
            task_id=task.id, title=(task.title or "").strip(),
            status=task.status, window_start=start, window_end=end,
            span_days=span, links=links[:top_n],
        ))
    return results


def refresh_suggestions(session: Session, cfg: Config, *,
                        team_id: int | None = None, top_n: int = 3) -> dict:
    """Motorun önerilerini DB'ye yazar. İNSAN KARARINA DOKUNMAZ.

    Bu fonksiyonun tek kritik kuralı: `confirmed`/`rejected` bir satır asla
    güncellenmez ve asla silinmez. Aksi hâlde her senkron, kullanıcının
    reddettiği eşleşmeyi geri getirir ve onay mekanizması anlamsızlaşır.
    """
    stats = {"suggested": 0, "already_decided": 0, "existing": 0}
    now = datetime.now(timezone.utc)

    existing: dict[tuple[int, int], TaskCommitLink] = {
        (row.task_id, row.commit_id): row
        for row in session.scalars(select(TaskCommitLink))
    }

    for group in link_tasks(session, cfg, team_id=team_id, top_n=top_n):
        for link in group.links:
            key = (group.task_id, link.commit_id)
            row = existing.get(key)
            if row is not None:
                # Karar verilmişse dokunma; verilmemişse skoru tazele
                # (model/eşik değişmiş olabilir, öneri güncel kalsın).
                if row.status in DECIDED:
                    stats["already_decided"] += 1
                else:
                    row.score = link.score
                    row.in_window = link.in_window
                    stats["existing"] += 1
                continue
            session.add(TaskCommitLink(
                task_id=group.task_id, commit_id=link.commit_id,
                status="suggested", score=link.score,
                in_window=link.in_window, created_at=now,
            ))
            stats["suggested"] += 1

    session.commit()
    return stats


def decide(session: Session, task_id: int, commit_id: int, status: str,
           user_id: int | None = None) -> TaskCommitLink:
    """Bir bağı onaylar ya da reddeder. Kayıt yoksa elle bağ olarak yaratılır
    (kullanıcı motorun hiç önermediği bir commit'i bağlayabilmeli)."""
    if status not in DECIDED:
        raise ValueError(f"Geçersiz karar: {status!r} (confirmed|rejected)")
    row = session.scalar(select(TaskCommitLink).where(
        TaskCommitLink.task_id == task_id,
        TaskCommitLink.commit_id == commit_id,
    ))
    if row is None:
        row = TaskCommitLink(
            task_id=task_id, commit_id=commit_id,
            created_at=datetime.now(timezone.utc),
        )
        session.add(row)
    row.status = status
    row.decided_by = user_id
    row.decided_at = datetime.now(timezone.utc)
    session.commit()
    return row


def list_links(session: Session, task_id: int) -> list[dict]:
    """Bir task'ın KAYITLI bağlarını döner — embedding ÇAĞRISI YAPMAZ.

    Görüntüleme yolu bilerek matcher'dan ayrı: `link_tasks` her çağrısında
    tüm başlıkları yeniden gömer (yerel CPU modelinde saniyeler sürer ve
    zaman aşımına girebilir). Öneriler zaten DB'de duruyor; arayüz onları okur,
    yeniden hesaplamaz. Yeniden hesap yalnız senkronda (`refresh_suggestions`).
    """
    rows = session.scalars(select(TaskCommitLink).where(
        TaskCommitLink.task_id == task_id)).all()
    if not rows:
        return []
    commits = {
        c.id: c for c in session.scalars(select(Commit).where(
            Commit.id.in_([r.commit_id for r in rows])))
    }
    out = []
    for r in rows:
        c = commits.get(r.commit_id)
        out.append({
            "commit_id": r.commit_id,
            "sha": (c.sha[:8] if c else None),
            "message": _head(c.message if c else None)[:120],
            "committed_at": (c.committed_at.isoformat() if c and c.committed_at else None),
            "status": r.status,
            "score": r.score,
            "in_window": r.in_window,
            "decided_at": r.decided_at.isoformat() if r.decided_at else None,
        })
    # Onaylılar üstte, sonra skora göre: kullanıcı önce kararını görsün.
    out.sort(key=lambda x: (x["status"] != "confirmed", -(x["score"] or 0)))
    return out


def confirmed_commits(session: Session, task_id: int) -> list[Commit]:
    """Bir task'ın ONAYLANMIŞ commit'leri — AI analizinin tek girdisi.

    Öneriler bilerek dışarıda: analiz tahmine dayanmaz."""
    ids = session.scalars(select(TaskCommitLink.commit_id).where(
        TaskCommitLink.task_id == task_id,
        TaskCommitLink.status == "confirmed",
    )).all()
    if not ids:
        return []
    return list(session.scalars(select(Commit).where(Commit.id.in_(ids))))
