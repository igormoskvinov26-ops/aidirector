"""Журнал обзвона виден с другого компьютера через общий сервер — по номеру
клиента YCLIENTS, без имён и телефонов на сервере (02.11.2026)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.models import AppSetting, Base, Client, ContactAttempt, ContactTask
from app.services import client_base, hub


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


async def _звонок(session):
    session.add(Client(id=1, yclients_id=501, name="Иван Петров", phone="+79990000001"))
    session.add(ContactTask(id=1, client_id=1, group_code="lost", priority=5,
                            due_date=client_base.moscow_today(), status="done"))
    session.add(ContactAttempt(task_id=1, outcome="booked", channel="phone", actor_id="Дарья",
                               was_lost=True, created_at=datetime.now(UTC)))
    await session.commit()


@pytest.mark.asyncio
async def test_звонки_салона_видны_на_маке(session):
    await _звонок(session)
    документы = await hub._обзвон_в_документы(session, client_base.moscow_today())
    (ключ, звонки), = документы.items()
    assert ключ.startswith("calls:") and ключ.count(":") == 2       # свой документ у каждой машины
    assert "Иван" not in str(звонки) and "+7999" not in str(звонки)  # на сервер — без личных данных

    # «Мак»: своих звонков нет, другая установка, тот же клиент в своей базе.
    await session.execute(delete(ContactAttempt))
    (await session.get(AppSetting, hub.МАШИНА_KEY)).value = "mac00000"
    await session.commit()
    await hub._применить(session, ключ, звонки)
    журнал = await client_base.call_log(session, None, None)
    assert [r["name"] for r in журнал["rows"]] == ["Иван Петров"]
    assert журнал["counters"] == {"calls": 1, "booked": 1, "returned": 1}


@pytest.mark.asyncio
async def test_свой_звонок_не_двоится(session):
    await _звонок(session)
    документы = await hub._обзвон_в_документы(session, client_base.moscow_today())
    (ключ, звонки), = документы.items()
    await hub._применить(session, ключ.rsplit(":", 1)[0], звонки)  # старый общий документ
    assert len((await client_base.call_log(session, None, None))["rows"]) == 1


@pytest.mark.asyncio
async def test_звонок_с_другого_компьютера_помечен(session):
    """Звонок, отмеченный на Маке, в журнале салона не выдаётся за свой
    (разбор жалобы 22.11.2026: «попадают те, кому не звонили»)."""
    await _звонок(session)
    session.add(Client(id=2, yclients_id=502, name="Пётр", phone="+79990000002"))
    await session.commit()
    сейчас = datetime.now(UTC).isoformat()
    чужой = [{"yclients_id": 502, "at": сейчас, "outcome": "no_answer", "group_code": "lost",
              "admin": "Дарья", "was_lost": False, "verification": None, "record_id": None}]
    await hub._применить(session, f"calls:{сейчас[:7]}:другаямашина", чужой)
    await session.commit()

    строки = (await client_base.call_log(session, None, None))["rows"]
    по_номеру = {r["yclients_id"]: r for r in строки}
    assert по_номеру[501]["source"] == "own"
    assert по_номеру[502]["source"] == "other" and по_номеру[502]["name"] == "Пётр"
