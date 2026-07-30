"""Projelerim — yerel klasör kaynağı.

Odak: YOL DOĞRULAMASI. Kullanıcı sunucuda bir yol yazıyor; doğrulama zayıfsa
panele girebilen herkes sunucudaki herhangi bir deponun commit mesajlarını
okuyabilir. Bu yüzden testlerin çoğu "izin verilmemeli" tarafında.
"""
from __future__ import annotations

import subprocess

import pytest

from app.core.config import Config
from app.services.local_git import (
    LocalRepoError,
    fetch_local_commits,
    resolve_local_repo,
)


def _git_repo(path, dosya="a.txt", mesaj="ilk commit"):
    """Gerçek bir git deposu kurar — parse'ı sahte çıktıyla değil git'in
    kendi çıktısıyla doğrulamak için."""
    path.mkdir(parents=True, exist_ok=True)
    run = lambda *a: subprocess.run(["git", "-C", str(path), *a], capture_output=True, check=True)  # noqa: E731
    run("init", "-q")
    run("config", "user.email", "kod@ornek.local")
    run("config", "user.name", "Kod Yazan")
    (path / dosya).write_text("icerik\n", encoding="utf-8")
    run("add", ".")
    run("commit", "-q", "-m", mesaj)
    return path


def _cfg(*roots) -> Config:
    cfg = Config()
    cfg.projects.local_roots = [str(r) for r in roots]
    return cfg


def test_izinli_kok_tanimli_degilse_ozellik_kapalidir(tmp_path):
    """Varsayılan KAPALI: kurulumda kendiliğinden açılmamalı."""
    repo = _git_repo(tmp_path / "repo")
    with pytest.raises(LocalRepoError, match="kapalı"):
        resolve_local_repo(str(repo), Config())


def test_izinli_kok_altindaki_git_deposu_kabul_edilir(tmp_path):
    repo = _git_repo(tmp_path / "kokler" / "projem")
    cozulen = resolve_local_repo(str(repo), _cfg(tmp_path / "kokler"))
    assert cozulen == repo.resolve()


def test_kokun_disindaki_yol_reddedilir(tmp_path):
    _git_repo(tmp_path / "kokler" / "izinli")
    disarisi = _git_repo(tmp_path / "baskasinin_klasoru")
    with pytest.raises(LocalRepoError, match="izinli kökler dışında"):
        resolve_local_repo(str(disarisi), _cfg(tmp_path / "kokler"))


def test_ust_dizine_tirmanma_engellenir(tmp_path):
    """'<izinli-kök>/../gizli' klasik kaçış. resolve() olmadan startswith
    kontrolü bu yolu izinli sanırdı."""
    _git_repo(tmp_path / "kokler" / "izinli")
    gizli = _git_repo(tmp_path / "gizli")
    kacis = tmp_path / "kokler" / ".." / "gizli"
    assert kacis.resolve() == gizli.resolve()  # gerçekten dışarı çıkıyor
    with pytest.raises(LocalRepoError, match="izinli kökler dışında"):
        resolve_local_repo(str(kacis), _cfg(tmp_path / "kokler"))


def test_kok_adiyla_baslayan_kardes_klasor_kabul_edilmez(tmp_path):
    """'/srv/repos' izinliyken '/srv/repos-gizli' düz startswith ile
    geçerdi — ayraç kontrolü olmadan sinsi bir açık."""
    kok = tmp_path / "repos"
    _git_repo(kok / "icerdeki")
    kardes = _git_repo(tmp_path / "repos-gizli")
    with pytest.raises(LocalRepoError, match="izinli kökler dışında"):
        resolve_local_repo(str(kardes), _cfg(kok))


def test_git_olmayan_klasor_reddedilir(tmp_path):
    kok = tmp_path / "kokler"
    duz = kok / "sadece-klasor"
    duz.mkdir(parents=True)
    with pytest.raises(LocalRepoError, match="git deposu değil"):
        resolve_local_repo(str(duz), _cfg(kok))


def test_olmayan_klasor_reddedilir(tmp_path):
    kok = tmp_path / "kokler"
    kok.mkdir()
    with pytest.raises(LocalRepoError, match="bulunamadı"):
        resolve_local_repo(str(kok / "yok"), _cfg(kok))


def test_bos_yol_reddedilir(tmp_path):
    with pytest.raises(LocalRepoError):
        resolve_local_repo("   ", _cfg(tmp_path))


def test_fetch_local_commits_github_ile_ayni_sekli_doner(tmp_path):
    """_sync iki kaynağı ayırt etmek zorunda kalmasın diye anahtarlar aynı."""
    repo = _git_repo(tmp_path / "repo", mesaj="feat: yerel kaynak ekle")
    commits = fetch_local_commits(repo, max_commits=10)
    assert len(commits) == 1
    c = commits[0]
    assert set(c) == {"sha", "author_name", "author_email", "message", "committed_at"}
    assert c["message"] == "feat: yerel kaynak ekle"
    assert c["author_email"] == "kod@ornek.local"
    assert c["author_name"] == "Kod Yazan"
    assert c["sha"] and c["committed_at"] is not None


def test_fetch_local_commits_max_commits_sinirlar(tmp_path):
    repo = _git_repo(tmp_path / "repo", mesaj="c1")
    for i in range(2, 5):
        (repo / f"f{i}.txt").write_text("x", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", f"c{i}"],
                       capture_output=True, check=True)
    assert len(fetch_local_commits(repo, max_commits=2)) == 2
    assert len(fetch_local_commits(repo, max_commits=100)) == 4
