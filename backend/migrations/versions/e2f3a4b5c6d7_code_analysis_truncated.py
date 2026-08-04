"""Kod analizinde prompt kırpılma bayrağı

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-08-04

Yerel LLM uçlarında prompt, modelin bağlam penceresine sığmadığında SESSİZCE
kesiliyordu: ölçümde 400 satırlık (config sınırı) bir diff ~7.700 token iken
Ollama yalnız 2050 token gördü, yani diff'in dörtte üçü modele hiç ulaşmadı —
model yine de 7 boyutta puan üretti. Artık kırpma gönderim ÖNCESİNDE yapılıyor
ve bu bayrakla beyan ediliyor: kırpılmış girdiye dayanan bir puan "tam analiz"
sanılmamalı.

Varsayılan false: geçmiş kayıtlar için kırpılıp kırpılmadığı BİLİNMİYOR ama o
kayıtlar zaten eski kod yoluyla üretildi; false burada "beyan edilmedi" demektir
ve uydurma bir bilgi taşımaz.
"""
from __future__ import annotations

import sqlalchemy as sa

from migrations.idempotent import kolon_dusur, kolon_ekle

revision = "e2f3a4b5c6d7"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent: kolon `ensure_schema_patches` tarafından zaten eklenmiş olabilir
    # (migration'sız demo kurulumu). batch_alter_table SQLite ALTER sınırı içindir.
    for tablo in ("code_analyses", "code_analysis_audit"):
        kolon_ekle(tablo, sa.Column(
            "truncated", sa.Boolean(), nullable=False, server_default=sa.false()
        ))


def downgrade() -> None:
    for tablo in ("code_analyses", "code_analysis_audit"):
        kolon_dusur(tablo, "truncated")
