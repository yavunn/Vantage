"""Metrik sorguları için indeksler

Revision ID: c6d7e8f9a0b1
Revises: b5c6d7e8f9a0
Create Date: 2026-08-04

`load_team_data` takımın TÜM commit/PR/task'ını belleğe çekip Python'da
filtreliyordu ve `compute_all` bunu takım başına 6 kez (pencere + 5 haftalık
kova) yapıyordu. Filtre SQL'e taşındı; bu indeksler o filtrenin tarama yerine
indeksten koşmasını sağlar.

metric_results indeksi upsert içindir: her metrik/kova için ayrı bir SELECT
yapılıyor ve tablo her senkronda yeniden doluyor.
"""
from __future__ import annotations


from migrations.idempotent import indeks_dusur, indeks_ekle

revision = "c6d7e8f9a0b1"
down_revision = "b5c6d7e8f9a0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    indeks_ekle("ix_commits_repo_committed", "commits", ["repo_id", "committed_at"])
    indeks_ekle("ix_prs_repo_merged", "pull_requests", ["repo_id", "merged_at"])
    indeks_ekle("ix_prs_repo_opened", "pull_requests", ["repo_id", "opened_at"])
    indeks_ekle("ix_tasks_team_missing", "tasks", ["team_id", "missing_since"])
    indeks_ekle("ix_metric_results_lookup", "metric_results",
                ["scope", "scope_id", "metric_key", "period"])


def downgrade() -> None:
    indeks_dusur("ix_metric_results_lookup", "metric_results")
    indeks_dusur("ix_tasks_team_missing", "tasks")
    indeks_dusur("ix_prs_repo_opened", "pull_requests")
    indeks_dusur("ix_prs_repo_merged", "pull_requests")
    indeks_dusur("ix_commits_repo_committed", "commits")
