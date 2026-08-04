"""Normalize kayıtları RAG chunk'larına çevirir.

Chunk YAPAY DEĞİLDİR — kaydın kendisidir. Uydurulmuş özet üretmiyoruz; kayıt
ne diyorsa o gömülür. Böylece cevabın dayandığı kaynak her zaman gösterilebilir.

KİŞİ ADI GEÇMEZ (İlke E). Chunk "kim yaptı"yı değil "ne oldu"yu anlatır:
yazar/atanan alanları metne hiç girmez. Bu, prompt'a isim sızmasını tek noktada
ve yapısal olarak engeller — sonraki katmanların dikkatli olmasına gerek kalmaz.

Diff İÇERİĞİ indekslenmez: hem maliyet (token) hem gizlilik. Commit'ten yalnız
mesaj ve değişen dosya YOLLARI alınır.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Config
from app.models import Commit, PullRequest, Repo, Task, Team

# Chunk başlığı: retrieval sonrası bağlamın kaybolmaması için her parçaya
# takım/tip/tarih damgası konur. Parça tek başına okunabilir olmalı.
_HEADER = "[{team}] [{kind}] [{when}]"

MAX_FILES_IN_CHUNK = 25  # dosya listesi kuyruğu chunk'ı boğmasın


@dataclass(frozen=True)
class Chunk:
    source_kind: str          # commit | pr | task
    source_id: int
    team_id: int | None
    chunk_index: int
    content: str

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


def _when(ts: datetime | None) -> str:
    return ts.date().isoformat() if ts else "tarihsiz"


def split_words(text: str, words: int, overlap: int) -> list[str]:
    """Metni örtüşmeli kelime pencerelerine böler.

    Örtüşme şart: bir cümlenin anlamı çoğu zaman önceki cümlede başlar; sert
    kesim o anlamı ikiye böler ve hiçbir parça tek başına yeterli olmaz.
    """
    tokens = text.split()
    if not tokens:
        return []
    if len(tokens) <= words:
        return [" ".join(tokens)]
    step = max(1, words - max(0, overlap))
    out: list[str] = []
    for start in range(0, len(tokens), step):
        window = tokens[start:start + words]
        if not window:
            break
        out.append(" ".join(window))
        if start + words >= len(tokens):
            break
    return out


def _emit(source_kind: str, source_id: int, team_id: int | None,
          header: str, body: str, cfg: Config) -> list[Chunk]:
    body = body.strip()
    if not body:
        return []
    parts = split_words(body, cfg.rag.chunk.words, cfg.rag.chunk.overlap)
    return [
        Chunk(source_kind, source_id, team_id, i, f"{header} {part}")
        for i, part in enumerate(parts)
    ]


def commit_chunks(session: Session, cfg: Config) -> list[Chunk]:
    """Commit → mesaj + değişen dosya yolları. Yazar bilgisi ALINMAZ."""
    repo_team = {
        r.id: (r.team_id, r.name) for r in session.scalars(select(Repo))
    }
    out: list[Chunk] = []
    for c in session.scalars(select(Commit)):
        team_id, repo_name = repo_team.get(c.repo_id, (None, "?"))
        files = [f for f in (c.changed_files or []) if isinstance(f, str)]
        extra = len(files) - MAX_FILES_IN_CHUNK
        file_part = ", ".join(files[:MAX_FILES_IN_CHUNK])
        if extra > 0:
            file_part += f" (+{extra} dosya daha)"
        body = (c.message or "").strip()
        if file_part:
            body = f"{body}\nDeğişen dosyalar: {file_part}"
        header = _HEADER.format(team=repo_name, kind="commit", when=_when(c.committed_at))
        out.extend(_emit("commit", c.id, team_id, header, body, cfg))
    return out


def pr_chunks(session: Session, cfg: Config) -> list[Chunk]:
    """PR → başlık + açılış/merge + review sayısı. Yazar/reviewer adı ALINMAZ."""
    repo_team = {r.id: (r.team_id, r.name) for r in session.scalars(select(Repo))}
    out: list[Chunk] = []
    for p in session.scalars(select(PullRequest)):
        team_id, repo_name = repo_team.get(p.repo_id, (None, "?"))
        bits = [(p.title or "").strip()]
        bits.append(f"Açılış: {_when(p.opened_at)}")
        if p.merged_at:
            bits.append(f"Merge: {_when(p.merged_at)}")
        elif p.closed_at:
            bits.append(f"Kapanış (merge edilmedi): {_when(p.closed_at)}")
        else:
            bits.append("Durum: hâlâ açık")
        n_reviews = len(p.reviews)
        bits.append(
            f"Review sayısı: {n_reviews}" if n_reviews else "Hiç review almamış"
        )
        header = _HEADER.format(team=repo_name, kind="PR", when=_when(p.opened_at))
        out.extend(_emit("pr", p.id, team_id, header, " · ".join(bits), cfg))
    return out


def task_chunks(session: Session, cfg: Config) -> list[Chunk]:
    """Task → başlık + statü + geçiş zinciri. Atanan kişi ALINMAZ."""
    teams = {t.id: t.name for t in session.scalars(select(Team))}
    out: list[Chunk] = []
    # Kaynakta artık olmayan kayıt indekslenmez: silinmiş bir kartın metnini
    # cevaba kaynak göstermek sistemin yalan söylemesi olurdu (indexer.py'deki
    # 'stale chunk' gerekçesiyle aynı ilke).
    for t in session.scalars(select(Task).where(Task.missing_since.is_(None))):
        bits = [(t.title or "").strip(), f"Statü: {t.status or 'belirsiz'}"]
        transitions = sorted(t.transitions, key=lambda tr: tr.changed_at)
        if transitions:
            chain = " → ".join(
                f"{tr.to_status} ({_when(tr.changed_at)})" for tr in transitions
            )
            bits.append(f"Akış: {chain}")
            span = (transitions[-1].changed_at - transitions[0].changed_at).days
            bits.append(f"İlk hareketten son harekete {span} gün")
        else:
            bits.append("Statü geçişi kaydı yok")
        header = _HEADER.format(
            team=teams.get(t.team_id, "takımsız"), kind="task", when=_when(t.created_at)
        )
        out.extend(_emit("task", t.id, t.team_id, header, " · ".join(bits), cfg))
    return out


def build_chunks(session: Session, cfg: Config) -> list[Chunk]:
    """Tüm normalize kayıtları chunk'a çevirir."""
    return [
        *commit_chunks(session, cfg),
        *pr_chunks(session, cfg),
        *task_chunks(session, cfg),
    ]
