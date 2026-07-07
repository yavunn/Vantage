"""SonarQube API QualityProvider'ı.

Kod kalitesi gözle değil araçla ölçülür (İlke C): coverage, complexity,
duplication, code smells. Ölçüler TAKIM/REPO seviyesindedir, kişiye
bağlanmaz.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import httpx

from app.adapters.base import NormalizedQualitySnapshot

METRIC_KEYS = "coverage,complexity,duplicated_lines_density,code_smells"


class SonarQubeProvider:
    def __init__(self, base_url: str, token_env: str, project_keys: list[str]):
        self.base_url = base_url.rstrip("/")
        self.token = os.environ.get(token_env, "")
        self.project_keys = project_keys

    def fetch_snapshots(self) -> list[NormalizedQualitySnapshot]:
        out: list[NormalizedQualitySnapshot] = []
        now = datetime.now(timezone.utc)
        with httpx.Client(base_url=self.base_url, auth=(self.token, ""), timeout=30) as client:
            for key in self.project_keys:
                resp = client.get(
                    "/api/measures/component",
                    params={"component": key, "metricKeys": METRIC_KEYS},
                )
                if resp.status_code != 200:
                    continue  # tek proje hatası senkronu düşürmez
                measures = {
                    m["metric"]: m.get("value")
                    for m in resp.json().get("component", {}).get("measures", [])
                }

                def num(name: str) -> float | None:
                    val = measures.get(name)
                    try:
                        return float(val) if val is not None else None
                    except ValueError:
                        return None

                smells = num("code_smells")
                out.append(
                    NormalizedQualitySnapshot(
                        repo_name=key,
                        taken_at=now,
                        coverage=num("coverage"),
                        complexity=num("complexity"),
                        duplication=num("duplicated_lines_density"),
                        code_smells=int(smells) if smells is not None else None,
                    )
                )
        return out
