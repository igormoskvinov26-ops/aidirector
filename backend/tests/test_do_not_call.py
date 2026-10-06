"""«НЕ ЗВОНИТЬ!»: помеченный клиент уходит из обзвона и не возвращается."""

from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.models import Client, ContactAttempt, ContactTask
from app.services import client_base


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_пометка_убирает_задачу_и_не_даёт_вернуться(session, monkeypatch):
    session.add(Client(id=1, yclients_id=1001, name="Иван", phone="+7999"))
    await session.flush()
    session.add(ContactTask(client_id=1, group_code="risk", priority=3, due_date=date.today(), status="open"))
    await session.commit()

    r = await client_base.set_do_not_call(session, 1, True, "Виктор")
    assert r["tasks_removed"] == 1
    c = await session.get(Client, 1)
    assert c.do_not_call and c.do_not_call_by == "Виктор"

    async def профили(_s):
        return {1: {"segment": "risk"}}

    monkeypatch.setattr(client_base, "build_client_profiles", профили)
    итог = await client_base.refresh_tasks(session)
    assert итог["tasks_created"] == 0
    assert (await session.execute(select(ContactTask))).scalars().all() == []

    await client_base.set_do_not_call(session, 1, False, None)
    assert (await client_base.refresh_tasks(session))["tasks_created"] == 1


@pytest.mark.asyncio
async def test_счётчик_звонков_за_сегодня(session):
    session.add(Client(id=1, yclients_id=1001, name="Иван", phone="+7999"))
    session.add(Client(id=2, yclients_id=1002, name="Пётр", phone="+7998"))
    await session.flush()
    session.add(ContactTask(id=5, client_id=1, group_code="risk", priority=3, due_date=date.today(), status="done"))
    session.add(ContactTask(id=6, client_id=2, group_code="lost", priority=3, due_date=date.today(), status="done"))
    for outcome, admin in (("booked", 7), ("no_answer", 7), ("no_booking", 8)):
        session.add(ContactAttempt(task_id=5, outcome=outcome, channel="phone", admin_staff_id=admin))
    session.add(ContactAttempt(task_id=6, outcome="booked", channel="phone", admin_staff_id=7))
    await session.commit()
    r = await client_base.calls_today(session, 7)
    assert r["salon"] == {"total": 4, "booked": 2, "no_booking": 1, "no_answer": 1, "returned_lost": 1}
    assert r["mine"] == {"total": 3, "booked": 2, "no_booking": 0, "no_answer": 1, "returned_lost": 1}


@pytest.mark.asyncio
async def test_звонки_за_день_для_закрытия_смены(session):
    """calls_for_day — то же, что считает calls_today на сегодня, но для
    любого дня и без истории рекордов: нужно закрытию смены и витрине."""
    session.add(Client(id=1, yclients_id=1001, name="Иван", phone="+7999"))
    await session.flush()
    session.add(ContactTask(id=5, client_id=1, group_code="lost", priority=3, due_date=date.today(), status="done"))
    session.add(ContactAttempt(task_id=5, outcome="booked", channel="phone"))
    await session.commit()
    r = await client_base.calls_for_day(session, date.today())
    assert r == {"total": 1, "booked": 1, "no_booking": 0, "no_answer": 0, "returned_lost": 1}
