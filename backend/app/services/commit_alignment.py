"""Commit mesajı ↔ yazılan kod eşleşmesi (mesaj-kod tutarlılığı).

SORU: "Commit mesajında söylenen şey, gerçekten değişen dosyalarla örtüşüyor mu?"
Örnek uyumsuzluk: `docs: readme güncellendi` ama değişen dosyalar `.py`;
`test: ...` ama hiç test dosyası yok; `fix(auth): ...` ama auth ile ilgisi olmayan
20 dosya değişmiş.

ETİK ÇERÇEVE: Bu bir dürüstlük denetimi DEĞİLDİR. Amaç, mesajların ileride
okunabilir/aranabilir olmasını sağlamak. Skor commit PRATİĞİNE aittir, kişiye
değil; ceza dili kullanılmaz. Kişiler arası kıyas için kullanılmaz.

Yöntem kural tabanlıdır (LLM gerekmez, maliyet yok, deterministik):
sadece commit mesajı + değişen dosya yolları + ekleme/silme sayıları kullanılır.
Diff içeriği okunmaz.
"""
from __future__ import annotations

import re

from app.core.i18n import tr_text

_TYPE = re.compile(
    r"^(?P<type>feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)"
    r"(\((?P<scope>[^)]+)\))?!?:\s*(?P<subject>.*)$",
    re.IGNORECASE,
)
# Mesajdan anlamlı sözcük çıkarımı için atılacak yaygın kelimeler (TR + EN)
_STOP = {
    "ve", "ile", "için", "bir", "bu", "the", "and", "for", "with", "add", "added", "ekle",
    "eklendi", "fix", "fixed", "update", "updated", "güncelle", "güncellendi", "remove",
    "removed", "sil", "silindi", "new", "yeni", "kod", "code", "test", "tests",
}

_TEST_PAT = re.compile(r"(^|/)(tests?|__tests__|spec)/|(_test|\.test|\.spec|_spec)\.", re.IGNORECASE)
_DOC_PAT = re.compile(r"\.(md|rst|adoc|txt)$|(^|/)docs?/", re.IGNORECASE)
_CI_PAT = re.compile(r"(^|/)\.github/|(^|/)\.gitlab-ci\.yml$|(^|/)(Jenkinsfile|azure-pipelines\.yml)$", re.IGNORECASE)
_BUILD_PAT = re.compile(
    r"(^|/)(Dockerfile|Makefile|package\.json|pyproject\.toml|requirements\.txt|"
    r"setup\.py|pom\.xml|build\.gradle|go\.mod|Cargo\.toml)$",
    re.IGNORECASE,
)
_STYLE_PAT = re.compile(r"\.(css|scss|less|sass)$", re.IGNORECASE)

# Uyumsuzluk başına düşülen puan (0..100 üzerinden)
_PENALTY = {"type_mismatch": 30, "scope_mismatch": 20, "subject_unrelated": 15, "too_broad": 15}


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşü_][A-Za-zÇĞİÖŞÜçğıöşü_0-9]{2,}", text or "")
    out = set()
    for w in words:
        low = w.lower()
        if low in _STOP:
            continue
        out.add(low)
        # camelCase / snake_case parçaları da eşleşsin
        for part in re.split(r"[_\-]|(?<=[a-z0-9])(?=[A-Z])", w):
            if len(part) >= 3 and part.lower() not in _STOP:
                out.add(part.lower())
    return out


def _path_tokens(paths: list[str]) -> set[str]:
    out: set[str] = set()
    for p in paths or []:
        for seg in re.split(r"[/\\.]", p):
            for part in re.split(r"[_\-]|(?<=[a-z0-9])(?=[A-Z])", seg):
                if len(part) >= 3:
                    out.add(part.lower())
    return out


def _type_expectation(ctype: str, paths: list[str]) -> tuple[bool, str | None]:
    """Commit tipiyle değişen dosya türleri örtüşüyor mu?
    Döner: (uyumlu_mu, uyumsuzsa açıklama)."""
    if not paths:
        return True, None
    t = ctype.lower()
    if t == "test":
        if not any(_TEST_PAT.search(p) for p in paths):
            return False, tr_text("`test:` yazılmış ama değişen dosyalar arasında test dosyası yok")
    elif t == "docs":
        if not all(_DOC_PAT.search(p) for p in paths):
            return False, tr_text("`docs:` yazılmış ama doküman dışı dosyalar da değişmiş")
    elif t == "ci":
        if not any(_CI_PAT.search(p) for p in paths):
            return False, tr_text("`ci:` yazılmış ama CI yapılandırma dosyası değişmemiş")
    elif t == "build":
        if not any(_BUILD_PAT.search(p) or _CI_PAT.search(p) for p in paths):
            return False, tr_text("`build:` yazılmış ama derleme/bağımlılık dosyası değişmemiş")
    elif t == "style":
        if not any(_STYLE_PAT.search(p) for p in paths):
            return False, tr_text("`style:` yazılmış ama stil dosyası değişmemiş (davranış değişmiş olabilir)")
    return True, None


def review_commit(commit: dict) -> dict:
    """commit: {sha, message, changed_files, additions, deletions}
    Döner: {sha, score(0..100)|None, aligned: bool|None, issues: [str], checked: bool}
    Değişen dosya bilgisi yoksa checked=False (veri yok — skor üretilmez)."""
    msg = (commit.get("message") or "").strip()
    paths = list(commit.get("changed_files") or [])
    sha = (commit.get("sha") or "")[:10]
    if not msg or not paths:
        return {
            "sha": sha, "score": None, "aligned": None, "checked": False,
            "issues": [],
            "reason": tr_text("Değişen dosya listesi ya da mesaj yok — eşleşme kontrol edilemedi"),
        }

    first = msg.splitlines()[0].strip()
    issues: list[str] = []
    penalty = 0

    m = _TYPE.match(first)
    subject = first
    scope_matched = False
    if m:
        subject = m.group("subject") or ""
        ok, why = _type_expectation(m.group("type"), paths)
        if not ok:
            issues.append(why)
            penalty += _PENALTY["type_mismatch"]
        scope = (m.group("scope") or "").strip().lower()
        if scope and scope not in {"*", "all"}:
            joined = " ".join(paths).lower()
            scope_parts = [s for s in re.split(r"[,\s/]+", scope) if len(s) >= 3]
            if scope_parts and any(sp in joined for sp in scope_parts):
                # Kapsam yolda geçiyor: mesaj zaten hangi modül olduğunu söylüyor.
                scope_matched = True
            elif scope_parts:
                issues.append(tr_text("Kapsam `({scope})` yazılmış ama değişen dosya "
                                      "yollarında karşılığı yok", scope=scope))
                penalty += _PENALTY["scope_mismatch"]

    # Konu satırı, dokunulan dosyalarla anlamsal olarak bağlantılı mı?
    subj_tokens = _tokens(subject)
    path_tokens = _path_tokens(paths)
    overlap = subj_tokens & path_tokens
    if not scope_matched:
        if not subj_tokens:
            # "update", "wip" gibi içeriksiz konu: hiçbir şeye bağlanamaz.
            issues.append(tr_text("Konu satırı içerik taşımıyor (ör. 'update') — hangi kodun neden "
                                  "değiştiği mesajdan anlaşılmıyor"))
            penalty += _PENALTY["subject_unrelated"]
        elif not overlap and len(paths) <= 20:
            issues.append(tr_text("Mesajdaki sözcükler değişen dosya/modül adlarıyla örtüşmüyor — "
                                  "hangi modülün değiştiği mesajdan anlaşılmıyor"))
            penalty += _PENALTY["subject_unrelated"]

    # Tek mesajla çok geniş değişiklik: mesaj kapsamı temsil edemez
    churn = (commit.get("additions") or 0) + (commit.get("deletions") or 0)
    if len(paths) >= 15 or churn >= 800:
        issues.append(tr_text("Tek commit'te {dosya} dosya / ~{satir} satır — mesaj bu kadar "
                              "değişikliği tek başına anlatamıyor, bölmek okunurluğu artırır",
                              dosya=len(paths), satir=churn))
        penalty += _PENALTY["too_broad"]

    score = max(0, 100 - penalty)
    return {
        "sha": sha, "score": score, "aligned": score >= 70, "checked": True,
        "issues": issues, "files": len(paths),
        "matched_terms": sorted(overlap)[:5],
    }


def alignment_summary(commits: list[dict], sample_limit: int = 5) -> dict:
    """Kişinin/takımın commit'lerinde mesaj-kod eşleşmesinin özeti.

    Döner: {score(0..100)|None, checked, total, aligned_ratio, summary, samples}
    Hiç kontrol edilebilir commit yoksa score None — veri uydurulmaz.
    """
    results = [review_commit(c) for c in commits or []]
    checked = [r for r in results if r["checked"]]
    if not checked:
        return {
            "score": None, "checked": 0, "total": len(results), "aligned_ratio": None,
            "summary": tr_text("Mesaj-kod eşleşmesi için değişen dosya bilgisi yok "
                               "(senkronda changed_files gerekli)."),
            "samples": [],
        }
    avg = round(sum(r["score"] for r in checked) / len(checked), 1)
    aligned = sum(1 for r in checked if r["aligned"])
    ratio = round(aligned / len(checked), 2)
    if avg >= 85:
        summary = tr_text("Commit mesajları yazılan kodla büyük ölçüde örtüşüyor.")
    elif avg >= 70:
        summary = tr_text("Mesajlar genelde koda uyuyor; birkaç commit'te kapsam mesajdan geniş.")
    else:
        summary = tr_text("Mesajlarla değişen kod sık sık ayrışıyor — mesaja hangi modülün ve "
                          "neden değiştiğini yazmak sonradan aramayı kolaylaştırır.")
    samples = sorted((r for r in checked if r["issues"]), key=lambda r: r["score"])[:sample_limit]
    return {
        "score": avg, "checked": len(checked), "total": len(results),
        "aligned_ratio": ratio, "summary": summary, "samples": samples,
    }
