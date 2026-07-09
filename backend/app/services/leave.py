"""İzin (Leave) yardımcıları — Faz 5.

Metrik entegrasyonunun asıl değeri buradadır: bir kişinin ONAYLI izin
günleri, metrik penceresinden hariç tutulur. "2 hafta izindeki kişide düşük
commit = anomali değil" ilkesi bu takvim üzerinden uygulanır.

Görünürlük/yetki kuralları API katmanındadır; burada yalnız veri sorgusu var.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Leave


def approved_leave_dates(
    session: Session, developer_id: int | None, start: datetime, end: datetime
) -> set[date]:
    """[start, end] penceresine düşen, developer'a ait ONAYLI izin takvim
    günlerini döner. Bekleyen/reddedilen talepler metriği ETKİLEMEZ —
    yalnız onaylı izin bağlam sayılır. developer bağı yoksa boş küme."""
    if developer_id is None:
        return set()
    start_d, end_d = start.date(), end.date()
    leaves = session.scalars(
        select(Leave).where(
            Leave.developer_id == developer_id,
            Leave.status == "approved",
            Leave.start_date <= end_d,
            Leave.end_date >= start_d,
        )
    ).all()
    days: set[date] = set()
    for lv in leaves:
        d = max(lv.start_date, start_d)
        last = min(lv.end_date, end_d)
        while d <= last:
            days.add(d)
            d += timedelta(days=1)
    return days
