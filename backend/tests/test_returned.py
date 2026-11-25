"""Возвращённые: кого обзвон поднял из потерянных, и как ведёт себя очередь."""

from datetime import date, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.models import Client, ContactAttempt, ContactTask
from app.services import client_base
from app.services.client_base import MOSCOW


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def _клиент_с_задачей(session, cid: int, сегмент: str, имя: str) -> int:
    session.add(Client(id=cid, yclients_id=1000 + cid, name=имя, phone=f"+7999000{cid:04d}"))
    await session.flush()
    задача = ContactTask(client_id=cid, group_code=сегмент, priority=5 if сегмент == "lost" else 2,
                         due_date=client_base.moscow_today(), status="open")
    session.add(задача)
    await session.commit()
    return задача.id


@pytest.mark.asyncio
async def test_записали_потерянного_он_попал_в_возвращённых(session):
    задача = await _клиент_с_задачей(session, 1, "lost", "Иван Потеряшка")
    обычная = await _клиент_с_задачей(session, 2, "risk", "Пётр Нериск")

    await client_base.record_outcome(session, задача, "booked", "phone", None, "Виктор", 7)
    await client_base.record_outcome(session, обычная, "booked", "phone", None, "Виктор", 7)

    итог = await client_base.returned_clients(session)
    assert итог["totals"] == {"total": 1, "confirmed": 0, "not_confirmed": 0, "pending": 1}
    assert [c["name"] for c in итог["clients"]] == ["Иван Потеряшка"]
    assert итог["clients"][0]["phone"] == "+79990000001"
    assert итог["admins"][0]["name"] == "Виктор" and итог["admins"][0]["total"] == 1
    сегодня = client_base.moscow_today().isoformat()
    assert [d for d in итог["days"] if d["date"] == сегодня] == [{"date": сегодня, "count": 1}]


@pytest.mark.asyncio
async def test_статус_подтверждения_приходит_из_сверки(session):
    задача = await _клиент_с_задачей(session, 1, "lost", "Иван")
    await client_base.record_outcome(session, задача, "booked", "phone", None, "Екатерина", 8)
    попытка = (await session.execute(
        __import__("sqlalchemy").select(ContactAttempt)
    )).scalars().one()
    попытка.verification_status = "confirmed"
    await session.commit()

    итог = await client_base.returned_clients(session)
    assert итог["totals"]["confirmed"] == 1 and итог["totals"]["pending"] == 0
    assert итог["clients"][0]["status"] == "confirmed"


@pytest.mark.asyncio
async def test_обработанные_остаются_в_очереди_и_уходят_вниз(session):
    первый = await _клиент_с_задачей(session, 1, "lost", "Первый")
    await _клиент_с_задачей(session, 2, "risk", "Второй")

    await client_base.record_outcome(session, первый, "booked", "phone", None, "Виктор", 7)
    очередь = await client_base.get_tasks(session)

    assert [t["client_name"] for t in очередь] == ["Второй", "Первый"]
    позвонили = очередь[-1]
    assert позвонили["called_today"] and позвонили["last_call_outcome"] == "booked"
    assert позвонили["last_call_at"] is not None


@pytest.mark.asyncio
async def test_не_дозвонились_дату_не_ставит(session):
    задача = await _клиент_с_задачей(session, 1, "lost", "Молчит")
    await client_base.record_outcome(session, задача, "no_answer", "phone", None, "Виктор", 7)
    очередь = await client_base.get_tasks(session)
    assert очередь[0]["last_call_at"] is None
    assert очередь[0]["last_call_outcome"] == "no_answer"
    assert не_в_возвращённых(await client_base.returned_clients(session))


def не_в_возвращённых(итог: dict) -> bool:
    return итог["totals"]["total"] == 0


@pytest.mark.asyncio
async def test_пересборка_очереди_не_задваивает_обзвоненных(session, monkeypatch):
    задача = await _клиент_с_задачей(session, 1, "lost", "Иван")
    await client_base.record_outcome(session, задача, "no_booking", "phone", None, "Виктор", 7)

    async def профили(_s):
        return {1: {"segment": "lost"}}

    monkeypatch.setattr(client_base, "build_client_profiles", профили)
    await client_base.refresh_tasks(session)
    очередь = await client_base.get_tasks(session)
    assert len(очередь) == 1 and очередь[0]["last_call_outcome"] == "no_booking"
