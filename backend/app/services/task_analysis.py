"""Bir işin (task) süreç analizi — ONAYLANMIŞ commit'lere dayanır.

Bu modülün varlık sebebi tek bir kural: analiz TAHMİNE DAYANMAZ.

Task↔commit bağı anlamsal benzerlikle tahmin ediliyor ve isabeti ~%50
(bkz. services/task_link.py). Öneriyi doğrudan analiz girdisi yapmak, sistemin
yanlış commit'e bakıp kendinden emin bir süreç yorumu yazması demekti. Bu,
RAG katmanındaki "zayıf bağlamla konuşma" kuralının aynısıdır: kaynağı
şüpheli bir cevap, cevapsızlıktan kötüdür.

Bu yüzden yalnız `confirmed` bağlar okunur. Onaylı bağ yoksa LLM ÇAĞRILMAZ,
'no_confirmed_links' döner ve arayüz kullanıcıyı önerileri onaylamaya yönlendirir.

KİŞİ ADI GEÇMEZ (İlke E): ne task'ın atananı ne commit'in yazarı prompt'a
girer. Analiz "kim yaptı"yı değil "süreç nasıl işledi"yi anlatır.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy.orm import Session

from app.core.config import Config
from app.core.i18n import tr_error
from app.models import Task
from app.services.code_analysis import mask_secrets
from app.services.task_link import as_utc, confirmed_commits, task_window

SYSTEM_PROMPT = """Sen bir yazılım süreç danışmanısın. Aşağıda bir işin (task) \
kaydı ve o işe ait olduğu İNSAN TARAFINDAN ONAYLANMIŞ commit'ler var.

ÇIKTI BİÇİMİ — ilk satır TAM OLARAK şu olmalı, başka hiçbir şey yazma:
UYUM: uyuyor
ya da
UYUM: kismi
ya da
UYUM: sapma
Sonra bir boş satır bırak ve analizini yaz.

UYUM ne demek: kartta TARİF EDİLEN iş ile onaylı commit'lerin ANLATTIĞI iş
örtüşüyor mu? 'uyuyor' = commit'ler kartın işini yapıyor. 'kismi' = işin bir
kısmı görünüyor ya da commit'ler kartın kapsamından geniş/dar. 'sapma' =
commit'ler kartta yazandan başka bir işi anlatıyor. Emin olamıyorsan 'kismi' de.
Bu bir SUÇLAMA DEĞİLDİR: sapma çoğu zaman kartın güncellenmemiş olması ya da
işin yol boyunca değişmiş olması demektir; bunu böyle yaz.

Kurallar:
- Yalnızca verilen kayıtlara dayan. Kayıtlarda olmayan bir şeyi ASLA uydurma.
- SADECE kayıtlarda GÖRÜNEN şeyi yaz. Kayıtta yoksa test aşamasından, code \
review'dan, tartışmadan, tekrar denemelerden BAHSETME — bunlar sana verilmedi.
- Uzunluk verinin miktarına göre olsun. Tek commit varsa BİR CÜMLE yaz. \
Cümle sayısını doldurmak için detay ÜRETME; az veri az cümle demektir.
- Kişilerden değil SÜREÇTEN bahset. Kimin yaptığı yazmıyor, sorma, tahmin etme.
- Suçlayıcı değil destekleyici dil kullan. Uzun süren bir iş "kusur" değil, \
"takım burada zorlanmış olabilir" demektir.
- Şunlardan yalnız KAYITLARDAN ÇIKARILABİLENLERİ söyle: işin ne kadar sürdüğü, \
kaç commit aldığı, hangi alanlara dokunulduğu, süre ile değişiklik hacminin uyumu.
- Commit'lere [1], [2] biçiminde atıf yap.
- Türkçe yanıtla. En fazla 5 cümle."""

MAX_FILES = 15  # dosya listesi prompt'u boğmasın (token freni)

# İlk satırdaki uyum yargısı. Model biçimi tutturamazsa yargı ÜRETİLMEZ
# (None kalır) — uydurulmuş bir "uyuyor" en kötü çıktıdır.
_ALIGNMENT_RE = re.compile(r"^\s*UYUM\s*:\s*(uyuyor|kismi|kısmi|sapma)\s*$",
                           re.IGNORECASE | re.MULTILINE)
ALIGNMENT_LABELS = {
    "uyuyor": "Kartla uyuyor",
    "kismi": "Kısmen uyuyor",
    "sapma": "Karttan sapmış",
}


def parse_alignment(text: str) -> tuple[str | None, str]:
    """(uyum, yargı satırı ayıklanmış metin). Biçim tutmazsa (None, metin)."""
    m = _ALIGNMENT_RE.search(text or "")
    if not m:
        return None, (text or "").strip()
    uyum = m.group(1).lower().replace("kısmi", "kismi")
    kalan = (text[: m.start()] + text[m.end():]).strip()
    return uyum, kalan


@dataclass
class TaskAnalysis:
    status: Literal["ok", "no_confirmed_links", "disabled", "error"]
    task_id: int
    text: str | None = None
    commits_used: list[str] = field(default_factory=list)
    reason: str | None = None
    # "uyuyor" | "kismi" | "sapma" | None (model biçimi tutturamadıysa)
    alignment: str | None = None
    alignment_label: str | None = None


def build_context(task: Task, commits: list) -> tuple[str, int]:
    """İş kaydı + onaylı commit'lerden bağlam bloğu. Secret'lar maskelenir."""
    start, end = task_window(task)
    span = (end - start).days if (start and end) else None
    lines = [
        f"İŞ: {(task.title or '').strip()}",
        f"Statü: {task.status or 'belirsiz'}",
    ]
    transitions = sorted(task.transitions, key=lambda t: t.changed_at)
    if transitions:
        chain = " → ".join(
            f"{t.to_status} ({t.changed_at.date().isoformat()})" for t in transitions
        )
        lines.append(f"Akış: {chain}")
        lines.append(f"İlk hareketten son harekete: {span} gün")
    else:
        lines.append("Statü geçişi kaydı yok")

    lines.append("\nONAYLANMIŞ COMMIT'LER:")
    masked_total = 0
    # Sıralamada tz normalize edilir: SQLite naive, PostgreSQL aware döner.
    ordered = sorted(commits, key=lambda x: as_utc(x.committed_at) or as_utc(start))
    for i, c in enumerate(ordered, start=1):
        head = (c.message or "").strip().splitlines()[0] if c.message else "(mesajsız)"
        safe, n = mask_secrets(head)
        masked_total += n
        when = c.committed_at.date().isoformat() if c.committed_at else "tarihsiz"
        files = [f for f in (c.changed_files or []) if isinstance(f, str)]
        extra = len(files) - MAX_FILES
        file_part = ", ".join(files[:MAX_FILES])
        if extra > 0:
            file_part += f" (+{extra} dosya daha)"
        churn = ""
        if c.additions is not None or c.deletions is not None:
            churn = f" · +{c.additions or 0}/-{c.deletions or 0} satır"
        lines.append(f"[{i}] {when} · {safe}{churn}")
        if file_part:
            lines.append(f"    dosyalar: {file_part}")
    return "\n".join(lines), masked_total


def analyze_task(session: Session, cfg: Config, task_id: int,
                 advisor=None) -> TaskAnalysis:
    """Bir işin süreç analizini üretir. Onaylı bağ yoksa LLM'e GİDİLMEZ."""
    task = session.get(Task, task_id)
    if task is None:
        return TaskAnalysis(status="error", task_id=task_id,
                            reason=tr_error("Task bulunamadı."))

    commits = confirmed_commits(session, task_id)
    if not commits:
        # LLM'e GİTMİYORUZ — bu dalın testi var.
        return TaskAnalysis(
            status="no_confirmed_links", task_id=task_id,
            reason=tr_error(
                "Bu iş için onaylanmış commit bağı yok. Analiz tahmine "
                "dayanmaz — önce önerilen bağları onaylayın."
            ),
        )

    if advisor is None:
        from app.llm.advisor import build_advisor
        advisor = build_advisor(cfg)
    if advisor is None:
        return TaskAnalysis(
            status="disabled", task_id=task_id,
            reason=tr_error("LLM katmanı kapalı (config: llm.enabled) — analiz üretilemez."),
        )

    context, _masked = build_context(task, commits)
    try:
        text = advisor.chat(SYSTEM_PROMPT, context)
    except Exception as e:  # noqa: BLE001 — uç 500 vermesin, sebep dönsün
        return TaskAnalysis(
            status="error", task_id=task_id,
            reason=tr_error("LLM çağrısı başarısız ({err}).", err=type(e).__name__),
        )

    ham = text if isinstance(text, str) else str(text)
    uyum, govde = parse_alignment(ham)
    return TaskAnalysis(
        status="ok", task_id=task_id,
        text=govde,
        commits_used=[c.sha[:8] for c in commits],
        alignment=uyum,
        alignment_label=ALIGNMENT_LABELS.get(uyum) if uyum else None,
    )
