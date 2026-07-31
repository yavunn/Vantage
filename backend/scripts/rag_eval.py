"""RAG retrieval kalite ölçümü — model/eşik değişikliklerini SAYIYLA kıyaslar.

Neden var: "cevap daha iyi göründü" bir ölçüm değildir. Embedding modeli ya da
eşik değiştirildiğinde iyileşme olup olmadığı ancak aynı soru kümesi üzerinde
ÖNCE/SONRA karşılaştırmasıyla söylenebilir.

Bu script SADECE retrieval'ı ölçer, LLM'i HİÇ ÇAĞIRMAZ. Sebep: cevap kalitesi
iki bağımsız katmanın çarpımıdır (doğru kayıt bulundu mu × model onu düzgün
özetledi mi). İkisini tek metriğe karıştırmak, hangisinin bozuk olduğunu
gizler. Üretim modelinin kalitesi ayrıca /ask ucuyla elle bakılır.

Embedding modeli KOMUT SATIRINDAN verilir, config'ten değil: eski modelin
skorlarını (baseline) config değiştirildikten sonra da ölçebilmek gerekir.
İndeks, chunk'ın gömüldüğü modele göre filtrelendiği için (index.py) her ölçüm
kendi vektör uzayında kalır.

Kullanım:
    python scripts/rag_eval.py --model nomic-embed-text --json before.json
    python scripts/rag_eval.py --model bge-m3           --json after.json
    python scripts/rag_eval.py --compare before.json after.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_config  # noqa: E402
from app.core.db import get_sessionmaker  # noqa: E402
from app.core.secrets import load_secrets  # noqa: E402
from app.services.rag.embedding import LocalEmbedding  # noqa: E402
from app.services.rag.index import InMemoryIndex  # noqa: E402

# Ölçüm derinliği: eşiklerden BAĞIMSIZ olmalı. min_score/top_k burada
# uygulanmaz — amaç "ilgili kayıt kaçıncı sırada" sorusunu yanıtlamak.
# Eşikler bu tablodaki skor dağılımına BAKILARAK seçilir, tersi değil.
DEPTH = 10


@dataclass(frozen=True)
class Case:
    """Bir soru + o soruya gerçekten cevap veren kaydı tanıyan desen.

    Beklenti chunk_id ile DEĞİL desenle tanımlanır: yeniden indeksleme id'leri
    değiştirir, desen ise kaydın İÇERİĞİNE bakar — ölçüm tekrar edilebilir kalır.
    """

    question: str
    expect: str  # chunk içeriğinde aranan regex (case-insensitive)


# Sorular bu repodaki gerçek commit/task kayıtlarına dayanır. Desenler DAR
# tutuldu: "test" gibi her yere uyan bir sözcük isabet oranını yapay şişirir.
CASES: list[Case] = [
    Case("Trello entegrasyonu için ne yapıldı?", r"trello"),
    Case("JWT ve oturum güvenliği tarafında hangi değişiklikler yapıldı?", r"jwt"),
    Case("Çalışan memnuniyet anketi özelliği nasıl eklendi?", r"survey|anket"),
    Case("İzin talebi ve onay sürecinde neler değişti?", r"leave|izin"),
    Case("Veritabanı migration'larında hangi sorun düzeltildi?", r"migration"),
    Case("GitHub üzerinden PR ve review metrikleri nasıl toplanıyor?", r"github"),
    Case("Frontend kod yapısında hangi refactor yapıldı?", r"app\.jsx|styles\.css"),
    Case("Kod kalitesi analizi hangi girdilerle çalışıyor?", r"code_analysis|kod analiz"),
]

# NEGATİF KONTROL — bu korpusun cevaplayamayacağı sorular.
# Bunlar olmadan min_score seçilemez: eşiğin işi ilgisiz sonucu ELEMEKTİR ve
# bunun ölçüsü "gerçekten alakasız bir soru kaç puan alıyor"dur. Yalnız pozitif
# örneklere bakarak seçilen eşik, sistemin bilmediğini bilmesini sağlamaz.
NEGATIVE: list[str] = [
    "Kubernetes cluster'ında pod autoscaling nasıl yapılandırıldı?",
    "Mobil uygulamanın App Store yayın süreci nasıl işliyor?",
    "Stripe ödeme entegrasyonunda hangi hatalar yaşandı?",
    "Depo stok sayımı süreci nasıl kurgulandı?",
]


@dataclass
class CaseResult:
    question: str
    expect: str
    rank: int | None          # ilk eşleşen kaydın sırası (1'den başlar), yoksa None
    scores: list[float]       # ilk DEPTH skorun listesi
    top_score: float
    spread: float             # top1 - topN: modelin AYIRT ETME gücü


def _spread(scores: list[float]) -> float:
    """İlk ve son skorun farkı. Küçükse model hiçbir kaydı gerçekten 'daha
    ilgili' bulmamış demektir — sıralama gürültüden ibarettir."""
    return round(scores[0] - scores[-1], 4) if len(scores) > 1 else 0.0


def run(model: str, base_url: str, team_id: int | None) -> list[CaseResult]:
    provider = LocalEmbedding(base_url, model)
    session = get_sessionmaker()()
    try:
        index = InMemoryIndex(session, model)
        out: list[CaseResult] = []
        for case in CASES:
            vec = provider.embed([case.question])[0]
            hits = index.search(vec, DEPTH, team_id)
            pattern = re.compile(case.expect, re.IGNORECASE)
            rank = next(
                (i for i, h in enumerate(hits, start=1) if pattern.search(h.content)),
                None,
            )
            scores = [round(h.score, 4) for h in hits]
            out.append(CaseResult(
                question=case.question, expect=case.expect, rank=rank,
                scores=scores, top_score=scores[0] if scores else 0.0,
                spread=_spread(scores),
            ))
        return out
    finally:
        session.close()


def run_negative(model: str, base_url: str, team_id: int | None) -> list[tuple[str, float]]:
    """Alakasız soruların en yüksek skorunu döner — eşiğin ÜST sınırı budur."""
    provider = LocalEmbedding(base_url, model)
    session = get_sessionmaker()()
    try:
        index = InMemoryIndex(session, model)
        out: list[tuple[str, float]] = []
        for q in NEGATIVE:
            hits = index.search(provider.embed([q])[0], 1, team_id)
            out.append((q, round(hits[0].score, 4) if hits else 0.0))
        return out
    finally:
        session.close()


def hit_at(results: list[CaseResult], k: int) -> float:
    if not results:
        return 0.0
    return sum(1 for r in results if r.rank is not None and r.rank <= k) / len(results)


def report(results: list[CaseResult], model: str) -> None:
    print(f"\n=== retrieval eval — embedding: {model} (derinlik {DEPTH}) ===\n")
    print(f"{'sıra':<6}{'top1':<8}{'yayılım':<10}soru")
    print("-" * 78)
    for r in results:
        rank = str(r.rank) if r.rank else "MISS"
        print(f"{rank:<6}{r.top_score:<8.4f}{r.spread:<10.4f}{r.question[:46]}")
    print("-" * 78)
    n = len(results)
    for k in (1, 3, 5, 8):
        print(f"hit@{k}: {hit_at(results, k):.0%}  ({sum(1 for r in results if r.rank and r.rank <= k)}/{n})")
    avg_spread = sum(r.spread for r in results) / n if n else 0.0
    avg_top = sum(r.top_score for r in results) / n if n else 0.0
    print(f"ortalama top1 skor: {avg_top:.4f}")
    print(f"ortalama yayılım  : {avg_spread:.4f}  (düşükse sıralama ayırt etmiyor)")

    # Eşik seçimi için ham veri: eşleşen ve eşleşmeyen kayıtların skorları
    # arasında gerçek bir boşluk var mı? min_score ancak buna bakarak seçilir.
    hit_scores = [r.scores[r.rank - 1] for r in results if r.rank]
    if hit_scores:
        print(f"\nEşik seçimi için — İLGİLİ kaydın skorları: "
              f"min {min(hit_scores):.4f} / ort {sum(hit_scores)/len(hit_scores):.4f} / "
              f"maks {max(hit_scores):.4f}")
    tail = [s for r in results for s in r.scores[3:]]
    if tail:
        print(f"                  4. sıra ve sonrası (çoğu ilgisiz): "
              f"min {min(tail):.4f} / ort {sum(tail)/len(tail):.4f} / maks {max(tail):.4f}")


def compare(before_path: Path, after_path: Path) -> None:
    before = [CaseResult(**r) for r in json.loads(before_path.read_text("utf-8"))["results"]]
    after = [CaseResult(**r) for r in json.loads(after_path.read_text("utf-8"))["results"]]
    b_model = json.loads(before_path.read_text("utf-8"))["model"]
    a_model = json.loads(after_path.read_text("utf-8"))["model"]
    print(f"\n=== ÖNCE ({b_model})  →  SONRA ({a_model}) ===\n")
    print(f"{'önce':<7}{'sonra':<7}soru")
    print("-" * 70)
    for b, a in zip(before, after, strict=True):
        bs = str(b.rank) if b.rank else "MISS"
        as_ = str(a.rank) if a.rank else "MISS"
        print(f"{bs:<7}{as_:<7}{b.question[:52]}")
    print("-" * 70)
    for k in (1, 3, 5, 8):
        print(f"hit@{k}: {hit_at(before, k):.0%} → {hit_at(after, k):.0%}")
    b_sp = sum(r.spread for r in before) / len(before)
    a_sp = sum(r.spread for r in after) / len(after)
    print(f"ortalama yayılım: {b_sp:.4f} → {a_sp:.4f}")


def main() -> None:
    ap = argparse.ArgumentParser(description="RAG retrieval kalite ölçümü")
    ap.add_argument("--model", help="embedding modeli (varsayılan: config)")
    ap.add_argument("--base-url", help="embedding ucu (varsayılan: config)")
    ap.add_argument("--team", type=int, default=None, help="takım id (varsayılan: hepsi)")
    ap.add_argument("--json", type=Path, help="sonucu bu dosyaya yaz")
    ap.add_argument("--compare", nargs=2, type=Path, metavar=("ÖNCE", "SONRA"),
                    help="iki json çıktısını kıyasla (ölçüm yapmaz)")
    args = ap.parse_args()

    if args.compare:
        compare(*args.compare)
        return

    load_secrets()
    cfg = get_config()
    model = args.model or cfg.rag.embedding.model
    base_url = args.base_url or cfg.rag.embedding.base_url

    results = run(model, base_url, args.team)
    report(results, model)

    negatives = run_negative(model, base_url, args.team)
    print("\n=== negatif kontrol (korpusta cevabı OLMAYAN sorular) ===")
    for q, score in negatives:
        print(f"  {score:.4f}  {q[:56]}")
    neg_max = max((s for _, s in negatives), default=0.0)
    pos_min = min((r.scores[r.rank - 1] for r in results if r.rank), default=0.0)
    print(f"\n  en yüksek ALAKASIZ skor : {neg_max:.4f}")
    print(f"  en düşük İLGİLİ skor    : {pos_min:.4f}")
    if pos_min > neg_max:
        print(f"  → ayrım var. min_score bu ikisinin arasında olmalı "
              f"({neg_max:.4f} < min_score < {pos_min:.4f}).")
    else:
        print("  → ayrım YOK: hiçbir min_score ilgiliyi ilgisizden ayıramaz. "
              "Eşik değil, embedding modeli değişmeli.")

    if args.json:
        args.json.write_text(
            json.dumps({"model": model, "results": [asdict(r) for r in results]},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nyazıldı: {args.json}")


if __name__ == "__main__":
    main()
