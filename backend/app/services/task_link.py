"""Task ↔ commit eşleştirme.

ÜÇ SİNYAL VAR ve ilki diğer ikisini gereksiz kılar:

0. KONVANSİYON (kesin). Commit mesajında kartın numarası yazıyorsa (`[#42]`,
   Jira'da `PROJ-123`) ortada tahmin yoktur: geliştirici bağı KENDİSİ beyan
   etmiştir. Bu bağ doğrudan `confirmed` yazılır ve o task için anlamsal
   tahmin ÜRETİLMEZ — kesin bilginin yanına tahmin koymak, ekranı kirletip
   kullanıcıyı "acaba bu mu?" diye düşündürmekten başka işe yaramaz.

   Bu yol, kart numarası kaynaktan çekildiği sürece çalışır (Trello `idShort`,
   `tasks.task_key`). Numarası olmayan ya da commit'lerde hiç anılmayan
   kartlarda aşağıdaki iki sinyale düşülür.

Konvansiyonun kullanılmadığı kayıtlarda kişi sinyali de yok — 26 task'ın
yalnız 2'sinde assignee dolu. Geriye iki sinyal kalıyor:

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

3. KİŞİ (yalnız GÖSTERİLİR, sıralamaya girmez). Kartın atananı ile commit'in
   yazarı aynı insansa bağ `same_person` işaretiyle döner. Bu sinyal ancak
   giriş hesapları hem Trello üyeliğine hem git e-postasına bağlıysa doğar
   (bkz. services/identity.py). Sıralama primi ÖLÇÜLDÜ ve fayda görülmediği
   için 0.0 bırakıldı — gerekçe PERSON_BONUS'un yanında.

Eşleştirme kesin değil TAHMİNdir; bu yüzden her bağ skorunu ve zaman
uyumunu taşır, çağıran taraf bunu kullanıcıya gösterebilsin.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Config
from app.models import Commit, Task, TaskCommitLink
from app.services.rag.embedding import cosine

DECIDED = ("confirmed", "rejected")

# --- Konvansiyon ayrıştırma ---------------------------------------------------
#
# `[#42]` — köşeli parantez ZORUNLU. Çıplak `#42` bilerek KABUL EDİLMEZ: git
# dünyasında `#42` neredeyse her zaman bir GitHub issue/PR numarasıdır ve bu
# depoda da öyle kullanılıyor. Çıplak biçimi kabul etmek, "fix #5" yazan bir
# commit'i 5 numaralı Trello kartına KESİN bağ diye işaretlerdi — yani sistemin
# kaçınmak için kurulduğu şeyi, uydurulmuş kesinliği, üretirdi.
_BRACKET_KEY_RE = re.compile(r"\[#(\d{1,6})\]")
# Jira biçimi (PROJ-123) kendi kendini tanımlar; parantez aranmaz.
_JIRA_KEY_RE = re.compile(r"\b([A-Z][A-Z0-9]{1,9}-\d{1,6})\b")

# Zaman primi: commit, task'ın hareket penceresine bu kadar gün yakınsa
# "zamanlama uyuyor" sayılır. Geniş tutuldu — bkz. modül başlığı.
WINDOW_MARGIN_DAYS = 7
# Yakınlık primi. Küçük tutuldu: zaman DESTEKLEYİCİ sinyal, karar verici değil.
# Büyütmek, aynı hafta yazılmış alakasız commit'i öne taşır.
TIME_BONUS = 0.03

# 3. KİŞİ. Kartın atananı ile commit'in yazarı aynı insan mı? Hesaplar hem
# Trello üyeliğine hem git e-postasına bağlıysa bu HESAPLANIR ve `same_person`
# olarak taşınır (ekranda "aynı kişi" rozeti; kişi bazlı görünümün de temeli).
#
# AMA SIRALAMAYA GİRMEZ — prim 0.0. Bu bir ihmal değil, ÖLÇÜM SONUCU:
#
#   scripts/task_link_eval.py --link 31=1   (6 onaylı bağ, 63 aday commit)
#     yalın benzerlik  ilk sıra 5/6 · ort. sıra 1.50
#     +kişi (0.05)     ilk sıra 5/6 · ort. sıra 1.50   → HİÇBİR DEĞİŞİKLİK
#
# Sebep yapısal: bu depoda tüm commit'ler tek yazara ait, dolayısıyla prim
# adayların HEPSİNE gidiyor ve hiçbir şeyi yeniden sıralayamıyor (ölçüm bunu
# ayrıca uyarı olarak basar). Ölçülmemiş bir fayda için sıralamayı oynatmak,
# bu sistemin kaçındığı şeyin ta kendisi olurdu: uydurulmuş kesinlik.
#
# BİRDEN ÇOK YAZARLI bir depoda sinyal ayırt edici hâle gelir. O zaman değeri
# yeniden ÖLÇÜN (kopyalamayın): `--person-bonus 0.05` ile koşup ilk sıra
# isabetinin gerçekten arttığını görmeden bu sabiti büyütmeyin.
#
# SERT FİLTRE zaten hiç düşünülmedi: kartların çoğunda atanan boş ve kartı açan
# ile kodu yazan çoğu zaman aynı kişi değil — sert filtre doğru eşleşmeleri
# sessizce keserdi (zaman penceresinde aynı hatadan dönülmüştü).
PERSON_BONUS = 0.0


@dataclass(frozen=True)
class CommitLink:
    commit_id: int
    sha: str
    message: str
    committed_at: datetime | None
    score: float          # anlamsal benzerlik (zaman/kişi primi HARİÇ)
    in_window: bool       # commit, task'ın hareket penceresine yakın mı
    rank_score: float     # sıralamada kullanılan bileşik skor
    # Commit'in yazarı, kartın atananlarından biri mi? Ekranda "aynı kişi"
    # rozeti olarak gösterilir; sıralamaya etkisi PERSON_BONUS kadardır (0.0).
    same_person: bool = False


@dataclass
class TaskLinks:
    task_id: int
    title: str
    status: str | None
    window_start: datetime | None
    window_end: datetime | None
    span_days: int | None
    links: list[CommitLink]


def task_developer_ids(task: Task) -> set[int]:
    """Kartın atananları: birincil (`assignee_id`) + tüm üyeler (task_assignees).

    İkisi birden okunur çünkü kaynaklar farklı: Trello kartı birden çok üyeye
    atanabilir, Jira'da tek atanan vardır. Çağıran hangisi olduğunu bilmek
    zorunda kalmasın."""
    ids = {a.developer_id for a in task.assignees if a.developer_id}
    if task.assignee_id:
        ids.add(task.assignee_id)
    return ids


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


def referenced_keys(message: str | None) -> set[str]:
    """Commit mesajında ANILAN task anahtarları (büyük harfe normalize).

    Mesajın TAMAMI taranır, ilk satırı değil: konvansiyon çoğu zaman gövdeye
    ("Refs [#42]") ya da footer'a yazılır."""
    if not message:
        return set()
    return {
        *(m.group(1) for m in _BRACKET_KEY_RE.finditer(message)),
        *(m.group(1).upper() for m in _JIRA_KEY_RE.finditer(message)),
    }


@dataclass(frozen=True)
class ConventionMatch:
    task_id: int
    commit_id: int
    in_window: bool


def convention_matches(
    tasks: list[Task], commits: list[Commit]
) -> tuple[list[ConventionMatch], list[str]]:
    """Commit mesajındaki anahtarlardan KESİN bağlar. Embedding KULLANMAZ.

    İki durumda bağ kurulmaz ve bu bilinçlidir:
    - Anılan anahtarın karşılığı yok (başka bir sistemin numarası olabilir) →
      sessizce atlanır; her `#`li sayıyı sahiplenmek yanlış bağ üretirdi.
    - Aynı anahtar birden çok task'a ait → Trello'da `idShort` board BAŞINA
      benzersizdir, iki board'da da 42 numaralı kart olabilir. Hangisi olduğu
      bilinmediğinde birini seçmek kura çekmektir; bağ kurulmaz ve durum
      UYARI olarak raporlanır ki kullanıcı neden bağ görmediğini bilsin.
    """
    by_key: dict[str, list[Task]] = {}
    for t in tasks:
        key = (t.task_key or "").strip().upper()
        if key:
            by_key.setdefault(key, []).append(t)

    matches: list[ConventionMatch] = []
    warnings: list[str] = []
    reported: set[str] = set()
    for c in commits:
        for key in referenced_keys(c.message):
            owners = by_key.get(key)
            if not owners:
                continue
            if len(owners) > 1:
                if key not in reported:
                    reported.add(key)
                    warnings.append(
                        f"Commit mesajlarında '{key}' anahtarı geçiyor ama bu anahtar "
                        f"{len(owners)} ayrı işe ait (Trello kart numarası board başına "
                        "benzersizdir) — hangisi olduğu bilinemediği için bağ kurulmadı."
                    )
                continue
            task = owners[0]
            start, end = task_window(task)
            lo = (as_utc(start) - timedelta(days=WINDOW_MARGIN_DAYS)) if start else None
            hi = (as_utc(end) + timedelta(days=WINDOW_MARGIN_DAYS)) if end else None
            at = as_utc(c.committed_at)
            matches.append(ConventionMatch(
                task_id=task.id, commit_id=c.id,
                in_window=bool(at and lo and hi and lo <= at <= hi),
            ))
    return matches, warnings


def link_tasks(session: Session, cfg: Config, *, team_id: int | None = None,
               min_score: float | None = None, top_n: int = 5,
               provider=None, exclude_task_ids: set[int] | None = None) -> list[TaskLinks]:
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
    skip = exclude_task_ids or set()
    tasks = [
        t for t in session.scalars(stmt)
        if (t.title or "").strip() and t.id not in skip
    ]
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
        atananlar = task_developer_ids(task)

        links: list[CommitLink] = []
        for commit_id, cvec in commit_vecs.items():
            score = cosine(tvec, cvec)
            if score < threshold:
                continue
            commit = commit_by_id[commit_id]
            at = commit.committed_at
            at_utc = as_utc(at)
            in_window = bool(at_utc and lo and hi and lo <= at_utc <= hi)
            # Kişi sinyali yalnız İKİ TARAF DA biliniyorsa oluşur: kartın
            # atananı yoksa ya da commit yazarı çözülememişse prim verilmez —
            # bilinmezliği "uymuyor" saymak, eşik altındaki doğru eşleşmeyi
            # cezalandırmak olurdu.
            same_person = bool(commit.author_id and commit.author_id in atananlar)
            links.append(CommitLink(
                commit_id=commit_id, sha=commit.sha,
                message=_head(commit.message)[:120],
                committed_at=at, score=round(score, 4), in_window=in_window,
                rank_score=round(
                    score
                    + (TIME_BONUS if in_window else 0.0)
                    + (PERSON_BONUS if same_person else 0.0),
                    4,
                ),
                same_person=same_person,
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
                        team_id: int | None = None, top_n: int = 3,
                        provider=None) -> dict:
    """Bağları DB'ye yazar: önce konvansiyon (kesin), sonra tahmin.

    Bu fonksiyonun tek kritik kuralı: `confirmed`/`rejected` bir satır asla
    güncellenmez ve asla silinmez. Aksi hâlde her senkron, kullanıcının
    reddettiği eşleşmeyi geri getirir ve onay mekanizması anlamsızlaşır. Bu
    kural konvansiyon bağları için de geçerlidir: geliştirici `[#42]` yazmış
    olsa bile insan o bağı reddettiyse insan haklıdır (kart numarası yanlış
    yazılmış olabilir).

    Konvansiyon adımı embedding ÇAĞIRMAZ ve kendi başına commit'lenir: yerel
    model kapalıyken de kesin bağlar kurulur, tahmin adımının başarısızlığı
    onları geri almaz.
    """
    stats = {"suggested": 0, "already_decided": 0, "existing": 0,
             "convention": 0, "warnings": []}
    now = datetime.now(timezone.utc)

    existing: dict[tuple[int, int], TaskCommitLink] = {
        (row.task_id, row.commit_id): row
        for row in session.scalars(select(TaskCommitLink))
    }

    # --- 0. Konvansiyon: commit mesajı kartın numarasını söylüyorsa ----------
    task_stmt = select(Task)
    if team_id is not None:
        task_stmt = task_stmt.where(Task.team_id == team_id)
    all_tasks = list(session.scalars(task_stmt))
    all_commits = list(session.scalars(select(Commit)))
    matches, warnings = convention_matches(all_tasks, all_commits)
    stats["warnings"] = warnings

    exact_task_ids: set[int] = set()
    for m in matches:
        exact_task_ids.add(m.task_id)
        key = (m.task_id, m.commit_id)
        row = existing.get(key)
        if row is not None and row.status in DECIDED:
            # İnsanın kararı konvansiyonu da ezer — bkz. docstring.
            stats["already_decided"] += 1
            continue
        if row is None:
            row = TaskCommitLink(task_id=m.task_id, commit_id=m.commit_id,
                                 created_at=now)
            session.add(row)
            existing[key] = row
        # Tahmin yok: skor da yok. 1.0 yazmak "%100 benzerlik ölçüldü"
        # gibi okunurdu; oysa burada benzerlik hiç hesaplanmadı.
        row.status = "confirmed"
        row.matched_by = "convention"
        row.score = None
        row.in_window = m.in_window
        stats["convention"] += 1
    session.commit()

    # --- 1. Anlamsal tahmin: konvansiyonla çözülmüş işler HARİÇ -------------
    #
    # Bu adım embedding ucuna bağlıdır ve o uç düşebilir. Hata yukarı
    # taşınırsa çağıran taraf tüm çağrıyı başarısız sayar ve yukarıda
    # commit'lenmiş KESİN bağların kurulduğunu öğrenemez — oysa onlar
    # embedding'e hiç ihtiyaç duymadı. Bu yüzden burada yakalanır.
    try:
        groups = link_tasks(session, cfg, team_id=team_id, top_n=top_n,
                            provider=provider, exclude_task_ids=exact_task_ids)
    except Exception as e:  # noqa: BLE001 — sebep uyarıya taşınır, iş kaybolmaz
        stats["warnings"].append(
            f"Anlamsal eşleştirme yapılamadı ({type(e).__name__}) — embedding "
            "sağlayıcısı erişilebilir mi? Konvansiyonla kurulan kesin bağlar "
            "etkilenmedi."
        )
        return stats

    for group in groups:
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
                    row.matched_by = "semantic"
                    stats["existing"] += 1
                continue
            session.add(TaskCommitLink(
                task_id=group.task_id, commit_id=link.commit_id,
                status="suggested", matched_by="semantic", score=link.score,
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
            # Motorun hiç önermediği bağ: ne tahmin ne konvansiyon — insan eli.
            matched_by="manual",
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
    # Kişi bilgisi SAKLANMAZ, burada türetilir: kimlik eşlemesi sonradan
    # yapıldığında eski satırlar da doğru rozeti gösterir. Saklansaydı bağ
    # kurulduğu andaki (çoğu zaman eksik) kimlik durumu donardı.
    task = session.get(Task, task_id)
    atananlar = task_developer_ids(task) if task is not None else set()
    out = []
    for r in rows:
        c = commits.get(r.commit_id)
        out.append({
            # Commit'i yazan, kartın atananlarından biri mi? Sıralamaya
            # GİRMEZ (bkz. PERSON_BONUS) — yalnız gösterilir.
            "same_person": bool(c and c.author_id and c.author_id in atananlar),
            "commit_id": r.commit_id,
            "sha": (c.sha[:8] if c else None),
            "message": _head(c.message if c else None)[:120],
            "committed_at": (c.committed_at.isoformat() if c and c.committed_at else None),
            "status": r.status,
            # Arayüz "geliştirici numarayı yazmış" ile "%73 benzer" arasındaki
            # farkı gösterebilmeli: ikisi aynı güvende değil.
            "matched_by": r.matched_by,
            "score": r.score,
            "in_window": r.in_window,
            "decided_at": r.decided_at.isoformat() if r.decided_at else None,
        })
    # Kesin bağlar en üstte, sonra onaylılar, sonra skora göre.
    out.sort(key=lambda x: (x["matched_by"] != "convention",
                            x["status"] != "confirmed", -(x["score"] or 0)))
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
