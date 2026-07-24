"""Anket soru editörü: düzenlenebilir taslak + döngü snapshot'ı

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-07-24

Admin soruları kendisi hazırlar. survey_question_templates = düzenlenebilir
taslak (sıralı, tek kaynak). survey_cycles.questions_json = döngü açılışında
dondurulan snapshot — taslak değişse bile açık/geçmiş döngü kendi sorularını
korur (agrega/anonimlik tutarlı). Portatif/migration'sız ortamda bu tablo
create_all ile, kolon ise _COLUMN_PATCHES ile de gelir.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Bu repoda survey tabloları create_all + _COLUMN_PATCHES ile de gelebiliyor
    # (alembic dışı). O yüzden idempotent: zaten varsa dokunma — "already exists"
    # ile çökme.
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table("survey_question_templates"):
        op.create_table(
            "survey_question_templates",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("key", sa.String(length=32), nullable=False),
            sa.Column("label", sa.String(length=200), nullable=False),
            sa.Column("type", sa.String(length=16), nullable=False, server_default="likert"),
            sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.UniqueConstraint("key", name="uq_survey_question_key"),
        )
    if insp.has_table("survey_cycles"):
        cols = {c["name"] for c in insp.get_columns("survey_cycles")}
        if "questions_json" not in cols:
            op.add_column("survey_cycles", sa.Column("questions_json", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if insp.has_table("survey_cycles"):
        cols = {c["name"] for c in insp.get_columns("survey_cycles")}
        if "questions_json" in cols:
            op.drop_column("survey_cycles", "questions_json")
    if insp.has_table("survey_question_templates"):
        op.drop_table("survey_question_templates")
