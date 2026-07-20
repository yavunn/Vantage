"""code_analyses + code_analysis_audit tabloları

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-20

AI kod analizi sonuçları (repo/dosya düzeyi, KİŞİ DEĞİL) + LLM'e giden verinin
denetim kaydı. Hash bazlı cache: aynı diff tekrar analiz edilmez.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "code_analyses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("repo_id", sa.Integer(), sa.ForeignKey("repos.id"), nullable=True),
        sa.Column("commit_sha", sa.String(64), nullable=True),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("diff_hash", sa.String(64), nullable=False),
        sa.Column("diff_lines", sa.Integer(), nullable=True),
        sa.Column("readability", sa.Integer(), nullable=True),
        sa.Column("complexity", sa.Integer(), nullable=True),
        sa.Column("maintainability", sa.Integer(), nullable=True),
        sa.Column("test_adequacy", sa.Integer(), nullable=True),
        sa.Column("security", sa.Integer(), nullable=True),
        sa.Column("code_smells", sa.Integer(), nullable=True),
        sa.Column("conventions", sa.Integer(), nullable=True),
        sa.Column("composite", sa.Float(), nullable=True),
        sa.Column("suggestions", sa.JSON(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("provider", sa.String(20), nullable=True),
        sa.Column("model", sa.String(60), nullable=True),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("repo_id", "diff_hash", name="uq_code_analysis"),
    )
    op.create_table(
        "code_analysis_audit",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("repo_id", sa.Integer(), sa.ForeignKey("repos.id"), nullable=True),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("diff_hash", sa.String(64), nullable=False),
        sa.Column("chars_sent", sa.Integer(), nullable=False),
        sa.Column("masked_secrets", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider", sa.String(20), nullable=True),
        sa.Column("model", sa.String(60), nullable=True),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("code_analysis_audit")
    op.drop_table("code_analyses")
