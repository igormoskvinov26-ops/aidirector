"""Запись вперёд по дням — основа и для «Записано до конца месяца» в закрытии
смены, и для контрольных точек (ЗП/аванс) на странице Владельца.

future_booked_by_day и future_booked_revenue должны видеть одни и те же
записи одинаково: второе — просто сумма первого (решение владельца
19.11.2026 — разбивка по дням понадобилась для контрольных дат внутри
месяца, итог на конец месяца должен остаться прежним).
"""

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.services import barber_month as bm

MOSCOW = ZoneInfo("Europe/Moscow")


def _запись(day: str, cost: float, attendance: int = 0, deleted: bool = False) -> dict:
    return {
        "datetime": f"{day}T12:00:00+03:00", "deleted": deleted, "visit_attendance": attendance,
        "services": [{"cost": cost}],
    }


class _Клиент:
    company_id = 1


@pytest.mark.asyncio
async def test_будущие_записи_группируются_по_дню(monkeypatch):
    записи = [
        _запись("2026-10-08", 700, attendance=0),
        _запись("2026-10-10", 300, attendance=2),
        _запись("2026-10-20", 10_000, attendance=0),
        _запись("2026-10-10", 999, attendance=1),  # выполненная — не считаем
        _запись("2026-10-08", 111, attendance=0, deleted=True),  # удалённая — не считаем
    ]

    async def fake_pages(client, path, start, end):
        return записи

    monkeypatch.setattr(bm, "pages", fake_pages)
    now = datetime(2026, 10, 5, tzinfo=MOSCOW)
    по_дням = await bm.future_booked_by_day(_Клиент(), now)
    assert по_дням == {
        date(2026, 10, 8): Decimal(700),
        date(2026, 10, 10): Decimal(300),
        date(2026, 10, 20): Decimal(10_000),
    }


@pytest.mark.asyncio
async def test_сумма_совпадает_со_старой_функцией(monkeypatch):
    записи = [_запись("2026-10-08", 700), _запись("2026-10-20", 10_000)]

    async def fake_pages(client, path, start, end):
        return записи

    monkeypatch.setattr(bm, "pages", fake_pages)
    now = datetime(2026, 10, 5, tzinfo=MOSCOW)
    итог = await bm.future_booked_revenue(_Клиент(), now)
    assert итог == Decimal(10_700)
