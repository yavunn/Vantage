"""Basit linter fallback QualityProvider'ı (SonarQube yoksa).

Config'teki linter komutunu repo dizininde çalıştırır, bulgu sayısını
code_smells olarak kaydeder. Coverage/complexity üretemez → o alanlar
None kalır ve ilgili göstergeler "veri yetersiz" olur. Entegrasyon
pluggable: SonarQube kurulunca config'te provider değiştirilir, kod aynı.
"""
from __future__ import annotations

import json
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from app.adapters.base import NormalizedQualitySnapshot


class LinterProvider:
    def __init__(self, command: str, repos: list[dict]):
        """command: JSON çıktı veren linter komutu (örn. ruff --output-format json).
        repos: git kaynağındaki [{name, path}] listesi — aynı repolar taranır."""
        self.command = command
        self.repos = repos

    def fetch_snapshots(self) -> list[NormalizedQualitySnapshot]:
        out: list[NormalizedQualitySnapshot] = []
        if not self.command:
            return out
        now = datetime.now(timezone.utc)
        for repo in self.repos:
            path = Path(repo.get("path", ""))
            if not path.exists():
                continue
            try:
                proc = subprocess.run(
                    shlex.split(self.command),
                    cwd=str(path),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=300,
                )
                findings = json.loads(proc.stdout or "[]")
                count = len(findings) if isinstance(findings, list) else None
            except (subprocess.SubprocessError, OSError, json.JSONDecodeError):
                count = None  # linter koşamadı → veri yok, uydurma yok
            out.append(
                NormalizedQualitySnapshot(
                    repo_name=repo["name"],
                    taken_at=now,
                    coverage=None,
                    complexity=None,
                    duplication=None,
                    code_smells=count,
                )
            )
        return out
