"""Anket temel tabloları (survey_cycles / responses / participations)

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-07-24

Bu tablolar başta yalnız create_all ile geliyordu (migration'da yoktu) — şema
tek doğru olsun diye alembic'e ekleniyor. IDEMPOTENT: create_all ya da önceki
kurulum tabloları oluşturmuşsa atlanır ("already exists" ile çökmez).
survey_cycles.questions_json burada dahildir (a7b8 tabloyu bulamayıp atlamış olabilir).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("survey_cycles"):
        op.create_table(
            "survey_cycles",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("key", sa.String(length=40), nullable=False),
            sa.Column("opens_at", sa.Date(), nullable=False),
            sa.Column("closes_at", sa.Date(), nullable=False),
            sa.Column("is_open", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("questions_json", sa.Text(), nullable=True),
            sa.UniqueConstraint("key", name="uq_survey_cycle_key"),
        )

    if not insp.has_table("survey_responses"):
        op.create_table(
            "survey_responses",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("cycle_id", sa.Integer(), sa.ForeignKey("survey_cycles.id"), nullable=False),
            sa.Column("ciphertext", sa.Text(), nullable=False),
            sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        )

    if not insp.has_table("survey_participations"):
        op.create_table(
            "survey_participations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("cycle_id", sa.Integer(), sa.ForeignKey("survey_cycles.id"), nullable=False),
            sa.Column("user_id", sa.Integer(),
                      sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.UniqueConstraint("cycle_id", "user_id", name="uq_survey_participation"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    for tbl in ("survey_participations", "survey_responses", "survey_cycles"):
        if insp.has_table(tbl):
            op.drop_table(tbl)
