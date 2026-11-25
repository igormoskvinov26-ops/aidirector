"""Результат звонка пишется именно тому клиенту, что на экране.

Жалоба владельца 22.11.2026: результаты обзвона иногда фиксировались
некорректно. Причина — каждая выгрузка удаляла все открытые задачи и
создавала их заново, номер задачи под открытой карточкой менялся, и кнопка
результата била в устаревший номер.
"""

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


async def _клиенты(session, *ids: int) -> None:
    for cid in ids:
        телефон = f"+7999000{cid:04d}"
        session.add(Client(id=cid, yclients_id=1000 + cid, name=f"К{cid}", phone=телефон))
    await session.commit()


def _профили(monkeypatch, сегменты: dict[int, str]) -> None:
    async def профили(_s):
        return {cid: {"segment": сегмент} for cid, сегмент in сегменты.items()}

    monkeypatch.setattr(client_base, "build_client_profiles", профили)


async def _задача(session, cid: int) -> ContactTask:
    return (await session.execute(
        select(ContactTask).where(ContactTask.client_id == cid, ContactTask.status == "open")
    )).scalars().one()


@pytest.mark.asyncio
async def test_номер_задачи_не_меняется_между_выгрузками(session, monkeypatch):
    await _клиенты(session, 1, 2)
    _профили(monkeypatch, {1: "lost", 2: "risk"})
    await client_base.refresh_tasks(session)
    было = {1: (await _задача(session, 1)).id, 2: (await _задача(session, 2)).id}

    итог = await client_base.refresh_tasks(session)

    assert итог["tasks_created"] == 0 and итог["tasks_removed"] == 0
    assert {1: (await _задача(session, 1)).id, 2: (await _задача(session, 2)).id} == было


@pytest.mark.asyncio
async def test_сменилась_группа_задача_пересоздаётся_только_у_него(session, monkeypatch):
    await _клиенты(session, 1, 2)
    _профили(monkeypatch, {1: "lost", 2: "risk"})
    await client_base.refresh_tasks(session)
    второй = (await _задача(session, 2)).id

    _профили(monkeypatch, {1: "risk", 2: "risk"})
    итог = await client_base.refresh_tasks(session)

    assert итог["tasks_created"] == 1 and итог["tasks_removed"] == 1
    assert (await _задача(session, 1)).group_code == "risk"
    assert (await _задача(session, 2)).id == второй


@pytest.mark.asyncio
async def test_устаревший_номер_задачи_пишется_клиенту_с_экрана(session, monkeypatch):
    await _клиенты(session, 1)
    _профили(monkeypatch, {1: "lost"})
    await client_base.refresh_tasks(session)
    старая = (await _задача(session, 1)).id
    await session.delete(await session.get(ContactTask, старая))
    await session.commit()

    итог = await client_base.record_outcome(
        session, старая, "booked", "phone", None, "Админ", client_id=1
    )

    assert итог["ok"]
    попытка = (await session.execute(select(ContactAttempt))).scalars().one()
    задача = await session.get(ContactTask, попытка.task_id)
    assert задача.client_id == 1


@pytest.mark.asyncio
async def test_чужой_номер_задачи_не_пишет_чужому_клиенту(session, monkeypatch):
    await _клиенты(session, 1, 2)
    _профили(monkeypatch, {1: "lost", 2: "lost"})
    await client_base.refresh_tasks(session)
    задача_первого = (await _задача(session, 1)).id

    # На экране — второй клиент, а номер задачи пришёл от первого.
    итог = await client_base.record_outcome(
        session, задача_первого, "do_not_call", "phone", None, "Админ", client_id=2
    )

    assert итог["ok"]
    первый = await session.get(Client, 1)
    второй = await session.get(Client, 2)
    assert not первый.do_not_call and первый.call_status is None
    assert второй.do_not_call and второй.call_status == "do_not_call"
    попытка = (await session.execute(select(ContactAttempt))).scalars().one()
    assert (await session.get(ContactTask, попытка.task_id)).client_id == 2


@pytest.mark.asyncio
async def test_без_номера_клиента_прежнее_поведение(session):
    итог = await client_base.record_outcome(session, 999, "booked", "phone", None, "Админ")
    assert итог == {"ok": False, "error": "task not found"}
