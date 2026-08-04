"""İŞ-16/İŞ-17: git_log adaptörünün sağlamlığı.

İŞ-16 — iki sessiz hata:
  * subprocess çıkış kodu kontrol edilmiyordu: git hata verdiğinde stdout boş
    gelir, sonuç "0 commit" olur ve panoda sebepsiz bir "veri yok" görünürdü.
  * encoding="utf-8" katıydı; UTF-8 olmayan bir commit mesajı UnicodeDecodeError
    fırlatıyor ve bu ValueError ailesinden olduğu için
    `except (SubprocessError, OSError)` onu YAKALAMIYOR, tüm senkron çöküyordu.

İŞ-17 — commit GÖVDESİ atılıyordu (%s): gövdeye yazılan görev referansları
("PROJ-123", "#42") task↔commit eşleşmesine hiç girmiyordu.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


@pytest.fixture()
def gecici_repo(tmp_path):
    """Gerçek bir git deposu — parser'ı taklit üzerinden değil git çıktısı üzerinden sınar."""
    repo = tmp_path / "depo"
    repo.mkdir()
    _git("init", "-q", cwd=repo)
    _git("config", "user.email", "dev@ornek.com", cwd=repo)
    _git("config", "user.name", "Dev", cwd=repo)
    return repo


def _commit(repo: Path, dosya: str, icerik: str, mesaj: str):
    (repo / dosya).write_text(icerik, encoding="utf-8")
    _git("add", dosya, cwd=repo)
    _git("commit", "-q", "-m", mesaj, cwd=repo)


def test_commit_govdesi_mesaja_dahil(gecici_repo):
    """İŞ-17: gövdedeki görev referansı kaybolmamalı."""
    from app.adapters.git_log import GitLogProvider

    _commit(gecici_repo, "a.py", "print(1)\n",
            "feat: yeni akış\n\nPROJ-123 numaralı iş için ilk adım.")
    p = GitLogProvider([{"name": "d", "path": str(gecici_repo)}])
    commits = p.fetch_commits()

    assert p.warnings == []
    assert len(commits) == 1
    assert "PROJ-123" in commits[0].message
    # Gövde eklenmesi numstat parse'ını BOZMAMALI (mesaj çok satırlı).
    assert commits[0].changed_files == ["a.py"]
    assert commits[0].additions == 1


def test_govde_numstat_ile_karismaz(gecici_repo):
    """Çok satırlı ve sayı içeren gövde, dosya listesine sızmamalı."""
    from app.adapters.git_log import GitLogProvider

    _commit(gecici_repo, "b.py", "x = 1\ny = 2\n",
            "fix: sayilar\n\n1\t2\tsahte/dosya.py\nGövde numstat'a benziyor.")
    commits = GitLogProvider([{"name": "d", "path": str(gecici_repo)}]).fetch_commits()

    assert commits[0].changed_files == ["b.py"]
    assert "sahte/dosya.py" not in (commits[0].changed_files or [])


def test_git_hatasi_sessiz_kalmaz(gecici_repo, monkeypatch):
    """İŞ-16: git sıfırdan farklı kodla dönerse sebep uyarıya taşınmalı."""
    from app.adapters import git_log as mod

    class _Proc:
        returncode = 128
        stdout = ""
        stderr = "fatal: your current branch 'main' does not have any commits yet"

    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **kw: _Proc())
    p = mod.GitLogProvider([{"name": "d", "path": str(gecici_repo)}])

    assert p.fetch_commits() == []
    assert p.warnings and "128" in p.warnings[0]
    assert "fatal" in p.warnings[0]


def test_tam_cekimde_bos_sonuc_hatadan_ayri_bildirilir(gecici_repo, monkeypatch):
    """TAM çekimde 'hata yok ama commit de yok' ayrı bir durumdur: repo yolu ya
    da dal seçimi yanlış olabilir, sessiz kalmamalı."""
    from app.adapters import git_log as mod

    class _Proc:
        returncode = 0
        stdout = ""      # git başarılı ama çıktı boş
        stderr = ""

    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **kw: _Proc())
    p = mod.GitLogProvider([{"name": "d", "path": str(gecici_repo)}])

    p.fetch_commits()
    assert p.warnings and "commit bulunamadı" in p.warnings[0]


def test_artimli_cekimde_bos_sonuc_uyari_uretmez(gecici_repo):
    """ARTIMLI çekimde yeni commit olmaması NORMALDİR.

    Uyarı üretmek iki kez yanlış olurdu: kullanıcıyı boşuna telaşlandırır ve
    uyarı üretildiği için ingest son-başarı damgasını İLERLETMEZ — yani her
    senkron aynı noktadan yeniden çeker ve artımlılık zamanla bozulur.
    (Bu, gerçek senkron koşusunda görüldü.)"""
    from datetime import datetime, timedelta, timezone

    from app.adapters.git_log import GitLogProvider

    _commit(gecici_repo, "a.py", "x\n", "ilk")
    p = GitLogProvider([{"name": "d", "path": str(gecici_repo)}])

    assert p.fetch_commits(since=datetime.now(timezone.utc) + timedelta(days=1)) == []
    assert p.warnings == []


def test_utf8_olmayan_mesaj_senkronu_dusurmez(gecici_repo):
    """İŞ-16: latin-1 yazılmış Türkçe bir mesaj UnicodeDecodeError fırlatıyordu
    ve bu istisna yakalanmadığı için TÜM senkron çöküyordu."""
    from app.adapters.git_log import GitLogProvider

    (gecici_repo / "c.py").write_text("x\n", encoding="utf-8")
    _git("add", "c.py", cwd=gecici_repo)
    # Mesajı doğrudan latin-1 baytlarıyla yaz (git bunu olduğu gibi saklar).
    mesaj_dosyasi = gecici_repo / "msg.txt"
    mesaj_dosyasi.write_bytes("düzeltme: ölçüm".encode("latin-1"))
    subprocess.run(["git", "commit", "-q", "-F", str(mesaj_dosyasi)],
                   cwd=gecici_repo, capture_output=True)
    mesaj_dosyasi.unlink()

    p = GitLogProvider([{"name": "d", "path": str(gecici_repo)}])
    commits = p.fetch_commits()  # ÇÖKMEMELİ

    assert len(commits) == 1
    assert commits[0].message  # bozuk karakterler değiştirilir, kayıt korunur


def test_tum_dallar_secenegi_argumana_yansir(gecici_repo, monkeypatch):
    """İŞ-17: dal kapsamı config'ten seçilebilmeli; varsayılan dar (HEAD)."""
    from app.adapters import git_log as mod

    yakalanan: list[list[str]] = []

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    def _run(args, **kw):
        yakalanan.append(args)
        return _Proc()

    monkeypatch.setattr(mod.subprocess, "run", _run)

    mod.GitLogProvider([{"name": "d", "path": str(gecici_repo)}]).fetch_commits()
    assert "--all" not in yakalanan[-1]

    mod.GitLogProvider([{"name": "d", "path": str(gecici_repo)}],
                       scan_all_branches=True).fetch_commits()
    assert "--all" in yakalanan[-1]
