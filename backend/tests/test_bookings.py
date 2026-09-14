"""Предстоящие записи — на настоящей базе.

Главное, что здесь проверяется: в список не попадает то, чего не будет.
Отменённые визиты, неявки и всё, что уже прошло, — мимо.
"""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.models import Client, Employee, Visit
from app.services.bookings import get_upcoming_bookings, get_upcoming_summary

NOW = datetime(2026, 9, 14, 12, 0)


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        s.add(Employee(id=1, yclients_id=101, name="Арташ"))
        s.add(Employee(id=2, yclients_id=102, name="Виктор"))
        s.add(Client(id=1, yclients_id=201, name="Иван", phone="+79990000001"))
        s.add(Client(id=2, yclients_id=202, name="Пётр", phone="+79990000002"))
        await s.commit()
        yield s
    await engine.dispose()


async def _add(session, *, vid, when, status, amount=2500, client=1, master=1):
    session.add(Visit(
        id=vid, yclients_id=1000 + vid, client_id=client, employee_id=master,
        datetime=when, status=status, total_amount=Decimal(amount),
    ))
    await session.commit()


@pytest.mark.asyncio
async def test_lists_future_scheduled_visits(session):
    await _add(session, vid=1, when=NOW + timedelta(hours=3), status="scheduled")
    await _add(session, vid=2, when=NOW + timedelta(days=2), status="scheduled", client=2, master=2)

    result = await get_upcoming_bookings(session, days=14, now=NOW)
    assert result["total_count"] == 2
    assert result["total_amount"] == 5000
    assert [d["date"] for d in result["days"]] == ["2026-09-14", "2026-09-16"]


@pytest.mark.asyncio
async def test_cancelled_and_no_show_are_excluded(session):
    """Ради этого всё и затевалось: несостоявшийся визит — не будущая запись."""
    await _add(session, vid=1, when=NOW + timedelta(hours=2), status="cancelled")
    await _add(session, vid=2, when=NOW + timedelta(hours=4), status="no_show")
    await _add(session, vid=3, when=NOW + timedelta(hours=6), status="scheduled")

    result = await get_upcoming_bookings(session, days=14, now=NOW)
    assert result["total_count"] == 1
    assert result["total_amount"] == 2500


@pytest.mark.asyncio
async def test_past_visits_are_excluded(session):
    await _add(session, vid=1, when=NOW - timedelta(hours=1), status="scheduled")
    await _add(session, vid=2, when=NOW + timedelta(hours=1), status="scheduled")

    result = await get_upcoming_bookings(session, days=14, now=NOW)
    assert result["total_count"] == 1


@pytest.mark.asyncio
async def test_horizon_is_respected(session):
    await _add(session, vid=1, when=NOW + timedelta(days=1), status="scheduled")
    await _add(session, vid=2, when=NOW + timedelta(days=20), status="scheduled")

    week = await get_upcoming_bookings(session, days=7, now=NOW)
    assert week["total_count"] == 1

    month = await get_upcoming_bookings(session, days=30, now=NOW)
    assert month["total_count"] == 2


@pytest.mark.asyncio
async def test_absurd_horizon_is_refused(session):
    with pytest.raises(ValueError):
        await get_upcoming_bookings(session, days=0, now=NOW)
    with pytest.raises(ValueError):
        await get_upcoming_bookings(session, days=5000, now=NOW)


@pytest.mark.asyncio
async def test_day_carries_masters_and_contacts(session):
    await _add(session, vid=1, when=NOW + timedelta(hours=2), status="scheduled")
    await _add(
        session, vid=2, when=NOW + timedelta(hours=3),
        status="scheduled", client=2, master=2,
    )

    day = (await get_upcoming_bookings(session, days=2, now=NOW))["days"][0]
    assert day["count"] == 2
    assert day["masters"] == ["Арташ", "Виктор"]
    assert day["records"][0]["client"] == "Иван"
    assert day["records"][0]["phone"] == "+79990000001"
    # Порядок внутри дня — по времени, иначе список нечитаем.
    assert day["records"][0]["time"] < day["records"][1]["time"]


@pytest.mark.asyncio
async def test_summary_splits_today_tomorrow_week(session):
    await _add(session, vid=1, when=NOW + timedelta(hours=2), status="scheduled")
    await _add(session, vid=2, when=NOW + timedelta(days=1), status="scheduled")
    await _add(session, vid=3, when=NOW + timedelta(days=4), status="scheduled")

    summary = await get_upcoming_summary(session, now=NOW)
    assert summary["today"]["count"] == 1
    assert summary["tomorrow"]["count"] == 1
    assert summary["week"]["count"] == 3


@pytest.mark.asyncio
async def test_empty_schedule_is_not_an_error(session):
    result = await get_upcoming_bookings(session, days=7, now=NOW)
    assert result["total_count"] == 0
    assert result["days"] == []
