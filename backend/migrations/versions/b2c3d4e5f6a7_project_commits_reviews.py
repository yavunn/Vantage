"""project_commits + commit_reviews tabloları

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-09

Kullanıcının eklediği GitHub projelerinin commitleri (izole) ve commit
pratiği değerlendirmeleri. user_projects tablosu zaten mevcut.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_commits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_project_id", sa.Integer(), sa.ForeignKey("user_projects.id"), nullable=False),
        sa.Column("sha", sa.String(64), nullable=False),
        sa.Column("author_name", sa.String(200), nullable=True),
        sa.Column("author_email", sa.String(320), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("additions", sa.Integer(), nullable=True),
        sa.Column("deletions", sa.Integer(), nullable=True),
        sa.Column("changed_files", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("user_project_id", "sha", name="uq_project_commit"),
    )
    op.create_table(
        "commit_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_project_id", sa.Integer(), sa.ForeignKey("user_projects.id"), nullable=False),
        sa.Column("commit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("provider", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("commit_reviews")
    op.drop_table("project_commits")
