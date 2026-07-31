"""Task ↔ commit bağı (öneri + insan onayı)

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-07-31

Bağ TAHMİNdir (anlamsal benzerlik), bu yüzden `status` ve `score` kolonları
şemanın parçası: bir bağın önerilmiş mi onaylanmış mı olduğu ve hangi skorla
önerildiği veri katmanında görünür olmalı. Reddedilen bağ da satır olarak
KALIR — silinseydi motor aynı yanlış öneriyi her senkronda tekrarlardı.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c8d9e0f1a2b3"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_commit_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("commit_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("in_window", sa.Boolean(), nullable=False),
        sa.Column("decided_by", sa.Integer(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.ForeignKeyConstraint(["commit_id"], ["commits.id"]),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "commit_id"),
    )


def downgrade() -> None:
    op.drop_table("task_commit_links")
