"""Görev ↔ commit eşleştirmesinin ilk sıra isabetini ÖLÇER.

NEDEN VAR: sıralamaya eklenen her prim (zaman, kişi) bir sayı ister ve o sayı
uydurulamaz. "Kişi sinyali eklendi, daha iyi oldu" cümlesi ölçülmeden yazılırsa
sistemin kendi kuralını (tahmini kesinlik gibi sunma) çiğnemiş olur.

ÖLÇÜM KÜMESİ = insanın ONAYLADIĞI bağlar (`task_commit_links.status =
'confirmed'`). Bunlar tahmin değil, karar: onay ekranında bir insan "evet bu
commit bu işin" demiştir. Konvansiyonla (`[#42]`) kurulmuş bağlar kümeden
ÇIKARILIR — onlar zaten sıralamaya hiç girmiyor, dahil etmek isabeti sahte
yükseltirdi.

ÖLÇÜLEN: doğru commit, o iş için üretilen sıralamada KAÇINCI çıkıyor. Dört
yapılandırma yan yana koşar: yalın benzerlik, +zaman primi, +kişi primi, ikisi.

VERİTABANINA YAZMAZ (salt okur). Embedding sağlayıcısı gerekir (yerel bge-m3):
    .venv\\Scripts\\python scripts\\task_link_eval.py
    .venv\\Scripts\\python scripts\\task_link_eval.py --person-bonus 0.08
"""
from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.core.config import get_config  # noqa: E402
from app.core.db import get_sessionmaker  # noqa: E402
from app.models import Commit, Task, TaskCommitLink  # noqa: E402
from app.services.rag.embedding import build_embedding_provider, cosine  # noqa: E402
from app.services.task_link import (  # noqa: E402
    PERSON_BONUS,
    TIME_BONUS,
    WINDOW_MARGIN_DAYS,
    _embed_batched,
    _head,
    as_utc,
    task_developer_ids,
    task_window,
)


def _ground_truth(session) -> list[tuple[Task, int]]:
    """(iş, doğru commit id) çiftleri — yalnız insan onayı, konvansiyon hariç."""
    out = []
    for row in session.scalars(select(TaskCommitLink).where(
        TaskCommitLink.status == "confirmed"
    )):
        if row.matched_by == "convention":
            continue  # sıralamaya hiç girmiyor
        task = session.get(Task, row.task_id)
        if task is None or not (task.title or "").strip():
            continue
        out.append((task, row.commit_id))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--person-bonus", type=float, default=PERSON_BONUS)
    ap.add_argument("--time-bonus", type=float, default=TIME_BONUS)
    ap.add_argument(
        "--link", action="append", default=[], metavar="KOPYA=HEDEF",
        help="Ölçüm sırasında bu kişi kayıtlarını AYNI insan say (ör. --link 31=1). "
             "Veritabanına DOKUNMAZ: kimlik eşlemesi yapılsaydı sonuç ne olurdu "
             "sorusunu cevaplar. Kimlikler bağlanmadan kişi sinyali hiç oluşmaz "
             "ve ölçüm 'etkisiz' der — oysa ölçtüğü şey eşlemenin yokluğudur.",
    )
    args = ap.parse_args()

    # kopya kişi id → hedef kişi id
    esleme: dict[int, int] = {}
    for ham in args.link:
        kopya, _, hedef = ham.partition("=")
        esleme[int(kopya)] = int(hedef)

    def coz(dev_id: int | None) -> int | None:
        return esleme.get(dev_id, dev_id) if dev_id else dev_id

    cfg = get_config()
    session = get_sessionmaker()()
    try:
        cift_listesi = _ground_truth(session)
        if not cift_listesi:
            print("Onaylanmış bağ yok — ölçülecek örnek kümesi boş. "
                  "Onay ekranından birkaç bağ onaylayıp tekrar çalıştırın.")
            return 1

        commits = [c for c in session.scalars(select(Commit)) if _head(c.message)]
        provider = build_embedding_provider(cfg)
        if provider is None:
            print("Embedding sağlayıcısı kapalı (rag.enabled?) — ölçüm yapılamaz.")
            return 1

        print(f"Örnek kümesi: {len(cift_listesi)} onaylı bağ · aday havuzu: {len(commits)} commit")
        commit_vecs = dict(zip(
            [c.id for c in commits],
            _embed_batched(provider, [_head(c.message) for c in commits]),
            strict=True,
        ))
        commit_by_id = {c.id: c for c in commits}
        task_vecs = _embed_batched(
            provider, [(t.title or "").strip() for t, _ in cift_listesi]
        )

        varyantlar = {
            "yalın benzerlik": (0.0, 0.0),
            "+zaman": (args.time_bonus, 0.0),
            "+kişi": (0.0, args.person_bonus),
            "+zaman +kişi": (args.time_bonus, args.person_bonus),
        }
        sonuc = {ad: [] for ad in varyantlar}
        kisi_sinyali_olan = 0
        ayirt_edicilik: list[tuple[int, int]] = []
        satirlar = []

        for (task, dogru_id), tvec in zip(cift_listesi, task_vecs, strict=True):
            start, end = task_window(task)
            lo = (as_utc(start) - timedelta(days=WINDOW_MARGIN_DAYS)) if start else None
            hi = (as_utc(end) + timedelta(days=WINDOW_MARGIN_DAYS)) if end else None
            atananlar = {coz(d) for d in task_developer_ids(task)}

            ham: dict[int, tuple[float, bool, bool]] = {}
            for cid, cvec in commit_vecs.items():
                c = commit_by_id[cid]
                at = as_utc(c.committed_at)
                in_window = bool(at and lo and hi and lo <= at <= hi)
                yazar = coz(c.author_id)
                ayni_kisi = bool(yazar and yazar in atananlar)
                ham[cid] = (cosine(tvec, cvec), in_window, ayni_kisi)

            if ham.get(dogru_id, (0, False, False))[2]:
                kisi_sinyali_olan += 1
            # AYIRT EDİCİLİK: prim, adayların HEPSİNE gidiyorsa sıralama hiç
            # değişmez. Tek yazarlı bir repoda kişi sinyali yapısal olarak
            # etkisizdir — "ölçtük, fayda yok" derken sebebini bilmek gerekir.
            primli = sum(1 for v in ham.values() if v[2])
            ayirt_edicilik.append((primli, len(ham)))

            siralar = {}
            for ad, (tb, pb) in varyantlar.items():
                sirali = sorted(
                    ham.items(),
                    key=lambda kv: kv[1][0] + (tb if kv[1][1] else 0.0)
                    + (pb if kv[1][2] else 0.0),
                    reverse=True,
                )
                sira = next(i for i, (cid, _) in enumerate(sirali, 1) if cid == dogru_id)
                sonuc[ad].append(sira)
                siralar[ad] = sira
            satirlar.append((task, dogru_id, ham.get(dogru_id), siralar))

        n = len(cift_listesi)
        print(f"\nKişi sinyali TAŞIYAN örnek: {kisi_sinyali_olan}/{n} "
              "(kartın atananı = commit'in yazarı, ikisi de kimliği bağlı)")
        tam_kaplama = sum(1 for primli, toplam in ayirt_edicilik if primli == toplam)
        if tam_kaplama:
            print(f"UYARI: {tam_kaplama}/{n} örnekte prim adayların HEPSİNE gidiyor "
                  "— sıralamayı değiştiremez (tek yazarlı repo). Kişi sinyali ancak "
                  "aday havuzunda birden çok yazar varken ayırt edicidir.")
        print("\n%-16s %-12s %-10s %s" % ("varyant", "ilk sıra", "ilk 3", "ort. sıra"))
        for ad, siralar in sonuc.items():
            ilk = sum(1 for s in siralar if s == 1)
            ilk3 = sum(1 for s in siralar if s <= 3)
            print("%-16s %-12s %-10s %.2f" % (
                ad, f"{ilk}/{n}", f"{ilk3}/{n}", sum(siralar) / n))

        print("\nÖrnek bazında (sıra: yalın → +zaman +kişi):")
        for task, dogru_id, bilgi, siralar in satirlar:
            c = commit_by_id.get(dogru_id)
            skor, pencere, kisi = bilgi or (0.0, False, False)
            print(f"  [{siralar['yalın benzerlik']:>2} → {siralar['+zaman +kişi']:>2}] "
                  f"skor={skor:.3f} pencere={'E' if pencere else 'H'} "
                  f"kişi={'E' if kisi else 'H'} :: {(task.title or '')[:42]!r} "
                  f"↔ {_head(c.message if c else '')[:42]!r}")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
