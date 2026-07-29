"""Hesap/İK çekirdek tabloları: users, leaves, user_projects, audit_logs, notifications

Revision ID: e1f2a3b4c5d6
Revises: 18731b1ad718
Create Date: 2026-07-29

Bu beş tablo şimdiye dek YALNIZCA create_all ile geliyordu; hiçbir migration
onları yaratmıyordu. Sonuç: temiz bir veritabanında `alembic upgrade head`
ikinci adımda çöküyordu (a1b2c3d4e5f6 → `ALTER TABLE users` ama users yok),
b8c9d0e1f2a3 ise survey_participations'ı olmayan users'a FK ile bağlamaya
çalışıyordu. Yani "sadece alembic ile kurulum" yolu fiilen kırıktı.

ZİNCİRDEKİ YERİ BİLİNÇLİ: initial_schema'nın hemen ardına konuldu, head'e
değil. Çünkü users'a dokunan migration'lar (a1b2 = must_change_password,
b8c9 = survey_participations FK, c9d0 = token_version) ondan SONRA geliyor;
tablo geç yaratılsaydı temiz kurulum yine aynı yerde çökerdi.

MEVCUT VERİTABANLARI ETKİLENMEZ: head'e (d0e1f2a3b4c5) damgalanmış bir DB
bu revizyonun gerisindedir, alembic onu hiç uygulamaz — tablolar zaten
create_all ile mevcuttur. Yine de her create_table `has_table` ile korunur:
create_all'la kurulmuş, damgası daha eski bir DB'de "already exists" ile
çökmez.

users burada TAM haliyle yaratılır (must_change_password ve token_version
dahil). Sonraki iki migration bu kolonları eklerken artık idempotenttir.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, None] = "18731b1ad718"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("users"):
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("email", sa.String(length=320), nullable=False, unique=True),
            sa.Column("password_hash", sa.String(length=200), nullable=True),
            sa.Column("role", sa.String(length=20), nullable=False),  # user | admin | hr
            # Baş yönetici: kimse silemez/rütbesini düşüremez. En fazla bir tane.
            sa.Column("is_owner", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("developer_id", sa.Integer(), sa.ForeignKey("developers.id"), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            # Geçici parola → ilk girişte değiştirme zorunlu (a1b2c3d4e5f6 ile aynı kolon).
            sa.Column("must_change_password", sa.Boolean(), nullable=False,
                      server_default=sa.false()),
            # Profil alanları — hiçbiri metriğe karışmaz.
            sa.Column("title", sa.String(length=120), nullable=True),
            sa.Column("phone", sa.String(length=40), nullable=True),
            sa.Column("timezone", sa.String(length=60), nullable=True),
            sa.Column("bio", sa.Text(), nullable=True),
            # İK alanları — performans metriğine karışmaz.
            sa.Column("hire_date", sa.Date(), nullable=True),
            sa.Column("annual_allowance", sa.Integer(), nullable=False, server_default="14"),
            # Login brute-force koruması.
            sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
            # Oturum geçersiz kılma (c9d0e1f2a3b4 ile aynı kolon).
            sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )

    if not insp.has_table("user_projects"):
        op.create_table(
            "user_projects",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("project_name", sa.String(length=200), nullable=False),
            sa.Column("source_type", sa.String(length=50), nullable=True),   # github
            sa.Column("source_url", sa.String(length=500), nullable=True),
            sa.Column("repo_id", sa.Integer(), sa.ForeignKey("repos.id"), nullable=True),
            sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_status", sa.String(length=20), nullable=True),   # ok | error
            sa.Column("last_detail", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )

    if not insp.has_table("leaves"):
        op.create_table(
            "leaves",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("developer_id", sa.Integer(), sa.ForeignKey("developers.id"), nullable=True),
            sa.Column("start_date", sa.Date(), nullable=False),
            sa.Column("end_date", sa.Date(), nullable=False),
            sa.Column("leave_type", sa.String(length=20), nullable=False),  # annual|sick|other
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False,
                      server_default="approved"),  # pending|approved|rejected
            sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            # Red gerekçesi — redde zorunlu, yalnız izin sahibi + yöneticiler görür.
            sa.Column("decision_note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )

    if not insp.has_table("audit_logs"):
        op.create_table(
            "audit_logs",
            sa.Column("id", sa.Integer(), primary_key=True),
            # Aktör silinse bile denetim kaydı KALIR (SET NULL) — e-posta metin olarak durur.
            sa.Column("actor_user_id", sa.Integer(),
                      sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("actor_email", sa.String(length=320), nullable=True),
            sa.Column("action", sa.String(length=40), nullable=False),
            sa.Column("target_user_id", sa.Integer(), nullable=True),
            sa.Column("target_email", sa.String(length=320), nullable=True),
            sa.Column("detail", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )

    if not insp.has_table("notifications"):
        op.create_table(
            "notifications",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(),
                      sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("kind", sa.String(length=40), nullable=False),  # trend_alarm|system|info
            sa.Column("severity", sa.String(length=10), nullable=False, server_default="info"),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("body", sa.Text(), nullable=True),
            # Aynı olay tekrar bildirilmesin diye tekilleştirme anahtarı.
            sa.Column("dedup_key", sa.String(length=200), nullable=True),
            sa.Column("link", sa.String(length=300), nullable=True),
            sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    # FK yönüne ters sırada düşür: users en sonda.
    for tbl in ("notifications", "audit_logs", "leaves", "user_projects", "users"):
        if insp.has_table(tbl):
            op.drop_table(tbl)
