"""Поиск по цифрам телефона, клиент из поиска в очереди и журнал обзвона."""

from datetime import timedelta

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


async def _клиенты(session):
    session.add_all([
        Client(id=1, yclients_id=101, name="Иван", phone="+7 (926) 123-45-67"),
        Client(id=2, yclients_id=102, name="Пётр", phone="79035554567"),
        Client(id=3, yclients_id=103, name="Олег", phone="+79161112233"),
    ])
    await session.commit()


@pytest.mark.asyncio
async def test_поиск_по_последним_цифрам_и_любой_записи_номера(session):
    await _клиенты(session)
    assert {r["name"] for r in await client_base.search_by_phone(session, "4567")} == {"Иван", "Пётр"}
    assert [r["name"] for r in await client_base.search_by_phone(session, "8926123")] == ["Иван"]
    assert [r["name"] for r in await client_base.search_by_phone(session, "926-123")] == ["Иван"]
    assert await client_base.search_by_phone(session, "45") == []  # меньше трёх цифр — пусто


@pytest.mark.asyncio
async def test_клиент_из_поиска_переживает_пересборку_очереди(session):
    await _клиенты(session)
    итог = await client_base.open_from_search(session, 3)
    assert итог["ok"]
    # повторное открытие не плодит задачи
    assert (await client_base.open_from_search(session, 3))["task_id"] == итог["task_id"]

    await client_base.refresh_tasks(session)
    задачи = (await session.execute(select(ContactTask).where(ContactTask.client_id == 3))).scalars().all()
    assert [з.id for з in задачи] == [итог["task_id"]]
    assert any(t["client_id"] == 3 for t in await client_base.get_tasks(session))


@pytest.mark.asyncio
async def test_журнал_все_кнопки_новые_сверху_и_счётчики(session):
    await _клиенты(session)
    сегодня = client_base.moscow_today()
    задачи = []
    for cid, группа in ((1, "lost"), (2, "risk"), (3, "due")):
        з = ContactTask(client_id=cid, group_code=группа, priority=1, due_date=сегодня, status="open")
        session.add(з)
        await session.flush()
        задачи.append(з.id)
    await session.commit()

    await client_base.record_outcome(session, задачи[0], "booked", "phone", None, "Аня", 1)
    await client_base.record_outcome(session, задачи[1], "booked", "phone", None, "Аня", 1)
    await client_base.record_outcome(session, задачи[2], "do_not_call", "phone", None, "Аня", 1)

    журнал = await client_base.call_log(session, сегодня, сегодня)
    assert журнал["counters"] == {"calls": 3, "booked": 2, "returned": 1}
    assert [r["name"] for r in журнал["rows"]] == ["Олег", "Пётр", "Иван"]  # новые сверху
    олег, пётр, иван = журнал["rows"]
    assert олег["outcome_label"] == "Не звонить" and олег["booking"] is None
    assert иван["booking"] == "pending" and иван["call_date"] == сегодня.isoformat()

    # вчерашний звонок в «сегодня» не попадает, во «всё время» — попадает
    попытка = (await session.execute(select(ContactAttempt).where(ContactAttempt.task_id == задачи[0]))).scalar_one()
    попытка.created_at = попытка.created_at - timedelta(days=1)
    await session.commit()
    assert (await client_base.call_log(session, сегодня, сегодня))["counters"]["calls"] == 2
    assert (await client_base.call_log(session, None, None))["counters"]["calls"] == 3


@pytest.mark.asyncio
async def test_теряем_сегодня_в_очереди_наверху_если_нет_записи_вперёд(session):
    from datetime import datetime, time
    from app.models.models import Employee, Visit
    from app.services.client_base import MOSCOW, LOST_AFTER_DAYS

    сегодня = client_base.moscow_today()
    session.add(Employee(id=1, yclients_id=1, name="Мастер"))
    # Редкий, но стабильный клиент: раз в 70 дней. По ритму звонить рано
    # («активный»), но сегодня 60-й день — по правилу салона он теряется.
    for cid, имя in ((1, "Редкий"), (2, "Записан вперёд"), (3, "Обычный риск")):
        session.add(Client(id=cid, yclients_id=100 + cid, name=имя, phone=f"+7900000000{cid}"))
    await session.flush()
    n = 0
    for cid in (1, 2):
        for k in range(5):
            n += 1
            day = сегодня - timedelta(days=LOST_AFTER_DAYS + 70 * k)
            session.add(Visit(yclients_id=n, client_id=cid, employee_id=1, status="completed",
                              datetime=datetime.combine(day, time(12), tzinfo=MOSCOW)))
    n += 1
    session.add(Visit(yclients_id=n, client_id=2, employee_id=1, status="scheduled",
                      datetime=datetime.combine(сегодня + timedelta(days=3), time(12), tzinfo=MOSCOW)))
    for k, d in enumerate((100, 140)):
        session.add(Visit(yclients_id=500 + k, client_id=3, employee_id=1, status="completed",
                          datetime=datetime.combine(сегодня - timedelta(days=d), time(12), tzinfo=MOSCOW)))
    await session.commit()

    await client_base.refresh_tasks(session)
    очередь = await client_base.get_tasks(session)
    по_имени = {t["client_name"]: t for t in очередь}
    assert "Записан вперёд" not in по_имени          # запись есть — не теряем
    assert по_имени["Редкий"]["lost_today"] and по_имени["Редкий"]["days_since_visit"] == LOST_AFTER_DAYS
    assert по_имени["Редкий"]["group_code"] == "losing"
    assert очередь[0]["client_name"] == "Редкий"       # наверху, пока не позвонили
    assert not по_имени["Обычный риск"]["lost_today"]


def test_ссылка_yclients_по_образцу_владельца(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "yclients_company_id", 2036703)
    образец = ("https://yclients.ru/clients/2036703/base/?fields%5B0%5D=name&fields%5B1%5D=surname"
               "&fields%5B2%5D=phone&fields%5B3%5D=email&fields%5B4%5D=sold_amount&fields%5B5%5D=visits_count"
               "&fields%5B6%5D=discount&fields%5B7%5D=last_visit_date&fields%5B8%5D=first_visit_date"
               "&fields%5B9%5D=tips_count&order_by=id&order_by_direction=desc&page=1&page_size=25&segment="
               "&operation=AND&filters%5B0%5D%5Boperation%5D=OR&filters%5B0%5D%5Bfilters%5D%5B0%5D%5Boperation%5D=AND"
               "&filters%5B0%5D%5Bfilters%5D%5B0%5D%5Bfilters%5D%5B0%5D%5Boperation%5D=AND"
               "&filters%5B1%5D%5Btype%5D=quick_search&filters%5B1%5D%5Bstate%5D%5Bvalue%5D=89990001122")
    assert client_base.ссылка_yclients("+7 (999) 000-11-22") == образец
    assert client_base.ссылка_yclients("89990001122") == образец
    assert client_base.ссылка_yclients("") is None
    assert client_base.шаблон_yclients().replace("{phone}", "89990001122") == образец


@pytest.mark.asyncio
async def test_журнал_показывает_дату_найденной_записи(session):
    from datetime import datetime, time
    from app.models.models import Employee, Visit
    from app.services.client_base import MOSCOW

    await _клиенты(session)
    сегодня = client_base.moscow_today()
    session.add(Employee(id=1, yclients_id=1, name="Мастер"))
    з = ContactTask(client_id=1, group_code="lost", priority=1, due_date=сегодня, status="open")
    session.add(з)
    await session.flush()
    когда = datetime.combine(сегодня + timedelta(days=2), time(15, 30), tzinfo=MOSCOW)
    session.add(Visit(yclients_id=777, client_id=1, employee_id=1, datetime=когда, status="scheduled"))
    await session.commit()
    await client_base.record_outcome(session, з.id, "booked", "phone", None, "Аня", 1)
    попытка = (await session.execute(select(ContactAttempt))).scalar_one()
    попытка.yclients_record_id, попытка.verification_status = 777, "confirmed"
    await session.commit()

    строка = (await client_base.call_log(session, сегодня, сегодня))["rows"][0]
    assert строка["booking"] == "confirmed"
    assert строка["booking_at"].startswith((сегодня + timedelta(days=2)).isoformat() + "T15:30")
    assert строка["admin"] == "Аня"


@pytest.mark.asyncio
async def test_вся_база_и_карточка_любого_клиента(session):
    await _клиенты(session)
    сегодня = client_base.moscow_today()
    session.add(ContactTask(client_id=2, group_code="risk", priority=3, due_date=сегодня, status="open"))
    await session.commit()

    база = await client_base.вся_база(session)
    assert {r["client_id"] for r in база} == {1, 2, 3}          # вся база, не только очередь
    assert база[0]["client_id"] == 2 and база[0]["in_queue"]   # очередь сверху
    assert not next(r for r in база if r["client_id"] == 1)["in_queue"]
    assert "yclients_url" not in база[0]                        # длинная ссылка не в каждой строке

    вне = await client_base.карточка_клиента(session, 1, "Аня")  # не в очереди
    assert вне["id"] is None and вне["client_name"] == "Иван" and вне["scripts"]
    в_очереди = await client_base.карточка_клиента(session, 2)
    assert в_очереди["id"] is not None and в_очереди["group_code"] == "risk"
    assert await client_base.карточка_клиента(session, 999) is None


@pytest.mark.asyncio
async def test_карточка_клиента_с_исключающим_тегом(session):
    """Тег «Переехал» убирает из очереди, но карточка из базы открывается."""
    from app.models.models import ClientTag, ClientTagLink

    await _клиенты(session)
    session.add(ClientTag(id=9, code="moved", name="Переехал", exclude_from_calls=True))
    session.add(ClientTagLink(client_id=1, tag_id=9))
    await session.commit()
    карточка = await client_base.карточка_клиента(session, 1, "Дарья")
    assert карточка is not None and карточка["client_name"] == "Иван"
