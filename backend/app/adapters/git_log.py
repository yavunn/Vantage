"""Yerel `git log` parse eden GitProvider (Katman 0).

GitLab/GitHub API'sine erişim olmayan on-prem ortamda bile çalışır:
şirket içindeki repo klonlarını doğrudan okur. PR verisi git log'da
olmadığından fetch_pull_requests boş döner — PR metrikleri bu durumda
"veri yetersiz" olarak raporlanır, sistem çökmez.
"""
from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

from app.adapters.base import NormalizedCommit, NormalizedPR

# Alan ayracı olarak kayıtlarda geçmesi imkansız bir dizi kullanılır
FIELD_SEP = "\x1f"
RECORD_SEP = "\x1e"
# %B = konu + GÖVDE. Gövde eskiden atılıyordu (%s) ve commit gövdesine yazılan
# görev referansları ("PROJ-123", "#42") task↔commit eşleşmesine hiç girmiyordu —
# oysa aynı iş için code_analysis.py:718 gövdeyi zaten alıyordu (tutarsızlık).
# Mesaj ÇOK SATIRLI olabildiği için en sona konur ve sonuna bir alan ayracı daha
# eklenir: numstat satırları o ayraçtan sonra başlar, parse belirsizliği kalmaz.
LOG_FORMAT = (
    f"{RECORD_SEP}%H{FIELD_SEP}%ae{FIELD_SEP}%an{FIELD_SEP}%aI{FIELD_SEP}%B{FIELD_SEP}"
)


class GitLogProvider:
    def __init__(self, repos: list[dict], scan_all_branches: bool = False):
        """repos: [{name, path, team}] — config'ten gelir.

        scan_all_branches: varsayılan False (yalnız HEAD). True yapılırsa
        `--all` ile merge edilmemiş dallardaki commit'ler de okunur. Varsayılan
        bilinçle dar: çoğu kurulumda ölçüm ana dalın akışıdır, `--all` kişisel
        deneme dallarını da metriğe sokar."""
        self.repos = repos
        self.scan_all_branches = scan_all_branches
        # Okunamayan repolar burada birikir; ingest bunu senkron sonucuna taşır.
        self.warnings: list[str] = []

    def fetch_commits(self, since: datetime | None = None) -> list[NormalizedCommit]:
        out: list[NormalizedCommit] = []
        self.warnings = []
        if not self.repos:
            self.warnings.append("Git repo listesi boş — çekilecek commit yok.")
            return out
        for repo in self.repos:
            name = repo.get("name") or "(isimsiz repo)"
            raw_path = repo.get("path") or ""
            if not raw_path:
                self.warnings.append(f"Repo '{name}': yol (path) tanımsız — commit çekilemedi.")
                continue
            path = Path(raw_path)
            if not (path / ".git").exists():
                # Erişilemeyen repo tüm senkronu düşürmez ama sessiz de kalmaz.
                self.warnings.append(
                    f"Repo '{name}': '{raw_path}' bir git deposu değil (.git yok) — commit çekilemedi."
                )
                continue
            args = ["git", "-C", str(path), "log", f"--pretty=format:{LOG_FORMAT}", "--numstat"]
            if self.scan_all_branches:
                args.append("--all")
            if since:
                args.append(f"--since={since.isoformat()}")
            try:
                proc = subprocess.run(
                    args, capture_output=True, text=True,
                    # errors="replace": UTF-8 OLMAYAN commit mesajı (eski depolar,
                    # latin-1 yazılmış Türkçe) UnicodeDecodeError fırlatıyordu ve
                    # bu ValueError ailesinden olduğu için aşağıdaki except onu
                    # YAKALAMIYOR, tüm senkron çöküyordu. code_analysis._run_git
                    # aynı işi zaten errors="replace" ile yapıyordu (tutarsızlık).
                    encoding="utf-8", errors="replace", timeout=120,
                )
            except (subprocess.SubprocessError, OSError) as e:
                self.warnings.append(f"Repo '{name}': git komutu çalıştırılamadı ({type(e).__name__}).")
                continue
            # Çıkış kodu KONTROL EDİLMELİ: git hata verdiğinde stdout boş gelir ve
            # sonuç "0 commit" olur. Sessiz kalırsa panoda "veri yok" görünür,
            # sebebi hiçbir yerde yazmaz.
            if proc.returncode != 0:
                hata = (proc.stderr or "").strip().splitlines()
                self.warnings.append(
                    f"Repo '{name}': git komutu hata verdi (kod {proc.returncode})"
                    + (f" — {hata[0][:200]}" if hata else "")
                )
                continue
            commits = self._parse(proc.stdout, repo["name"])
            if not commits and since is None:
                # "Hata yok ama kayıt da yok" ayrı bir durumdur: dal seçimi ya da
                # repo yolu yanlış olabilir. Hata mesajıyla karışmasın diye ayrı yazılır.
                #
                # ARTIMLI çekimde (since dolu) bu NORMALDİR — son senkrondan beri
                # commit atılmamış demektir; uyarı üretmek iki kez yanlış olurdu:
                # kullanıcıyı boşuna telaşlandırır ve uyarı ürettiği için
                # ingest son-başarı damgasını ilerletmez, yani artımlılık zamanla
                # bozulurdu (gerçek senkron koşusunda görüldü).
                self.warnings.append(
                    f"Repo '{name}': git okundu ama hiç commit bulunamadı."
                )
            out.extend(commits)
        return out

    def _parse(self, raw: str, repo_name: str) -> list[NormalizedCommit]:
        commits: list[NormalizedCommit] = []
        for record in raw.split(RECORD_SEP):
            record = record.strip()
            if not record:
                continue
            # Mesaj çok satırlı olabildiği için alanlara AYRAÇLA bölünür,
            # satırlara değil: son alan numstat bloğunu taşır.
            parts = record.split(FIELD_SEP)
            if len(parts) < 5:
                continue
            sha, email, name, date_iso, message = parts[:5]
            numstat = parts[5] if len(parts) > 5 else ""
            committed_at = None
            try:
                committed_at = datetime.fromisoformat(date_iso)
            except ValueError:
                pass  # bozuk tarih → None; metrik motoru bu kaydı düşer
            files: list[str] = []
            additions = deletions = 0
            for line in numstat.splitlines():
                parts = line.split("\t")
                if len(parts) == 3:
                    add, rem, fname = parts
                    files.append(fname)
                    # binary dosyalarda git "-" yazar
                    additions += int(add) if add.isdigit() else 0
                    deletions += int(rem) if rem.isdigit() else 0
            commits.append(
                NormalizedCommit(
                    repo_name=repo_name,
                    sha=sha,
                    author_key=email or None,
                    author_name=name or None,
                    committed_at=committed_at,
                    message=message.strip() or None,
                    changed_files=files or None,
                    additions=additions,
                    deletions=deletions,
                )
            )
        return commits

    def fetch_pull_requests(self, since: datetime | None = None) -> list[NormalizedPR]:
        return []  # git log'da PR yok; PR metrikleri "veri yetersiz" olur
