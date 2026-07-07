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
LOG_FORMAT = f"{RECORD_SEP}%H{FIELD_SEP}%ae{FIELD_SEP}%an{FIELD_SEP}%aI{FIELD_SEP}%s"


class GitLogProvider:
    def __init__(self, repos: list[dict]):
        """repos: [{name, path, team}] — config'ten gelir."""
        self.repos = repos

    def fetch_commits(self, since: datetime | None = None) -> list[NormalizedCommit]:
        out: list[NormalizedCommit] = []
        for repo in self.repos:
            path = Path(repo.get("path", ""))
            if not (path / ".git").exists():
                continue  # erişilemeyen repo tüm senkronu düşürmez
            args = ["git", "-C", str(path), "log", f"--pretty=format:{LOG_FORMAT}", "--numstat"]
            if since:
                args.append(f"--since={since.isoformat()}")
            try:
                raw = subprocess.run(
                    args, capture_output=True, text=True, encoding="utf-8", timeout=120
                ).stdout
            except (subprocess.SubprocessError, OSError):
                continue
            out.extend(self._parse(raw, repo["name"]))
        return out

    def _parse(self, raw: str, repo_name: str) -> list[NormalizedCommit]:
        commits: list[NormalizedCommit] = []
        for record in raw.split(RECORD_SEP):
            record = record.strip()
            if not record:
                continue
            lines = record.splitlines()
            head = lines[0].split(FIELD_SEP)
            if len(head) < 5:
                continue
            sha, email, name, date_iso, subject = head[:5]
            committed_at = None
            try:
                committed_at = datetime.fromisoformat(date_iso)
            except ValueError:
                pass  # bozuk tarih → None; metrik motoru bu kaydı düşer
            files: list[str] = []
            additions = deletions = 0
            for line in lines[1:]:
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
                    message=subject or None,
                    changed_files=files or None,
                    additions=additions,
                    deletions=deletions,
                )
            )
        return commits

    def fetch_pull_requests(self, since: datetime | None = None) -> list[NormalizedPR]:
        return []  # git log'da PR yok; PR metrikleri "veri yetersiz" olur
