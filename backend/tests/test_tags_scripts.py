"""Теги, скрипты и плановый перезвон (пакет задач владельца 16.10.2026)."""

from datetime import date, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.models import AppSetting, Client, ClientTag, ContactAttempt, ContactTask
from app.services import client_base, hub
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


async def _клиент(session, cid: int, сегмент: str = "lost", имя: str = "Клиент") -> int:
    session.add(Client(id=cid, yclients_id=1000 + cid, name=имя, phone=f"+7999000{cid:04d}"))
    await session.flush()
    задача = ContactTask(client_id=cid, group_code=сегмент,
                         priority=client_base.TASK_PRIORITY.get(сегмент, 1),
                         due_date=client_base.moscow_today(), status="open")
    session.add(задача)
    await session.commit()
    return задача.id


@pytest.mark.asyncio
async def test_тег_с_исключением_убирает_клиента_из_очереди(session):
    await _клиент(session, 1, имя="Переехавший")
    await _клиент(session, 2, имя="Обычный")
    теги = await client_base.tags_list(session)
    переехал = next(t for t in теги if t["exclude_from_calls"])

    до = await client_base.get_tasks(session)
    assert {t["client_name"] for t in до} == {"Переехавший", "Обычный"}

    await client_base.set_client_tag(session, 1, переехал["id"], True, "Виктор")
    после = await client_base.get_tasks(session)
    assert [t["client_name"] for t in после] == ["Обычный"]

    # Снимаем тег — клиент возвращается, ничего не потеряно.
    await client_base.set_client_tag(session, 1, переехал["id"], False, "Виктор")
    assert len(await client_base.get_tasks(session)) == 2


@pytest.mark.asyncio
async def test_варианты_разговора_и_приоритет_тега(session):
    """Скрипт — дерево из регламента; свой вариант тега встаёт первым."""
    await _клиент(session, 1, имя="Пётр")
    теги = await client_base.tags_list(session)
    акция = next(t for t in теги if t["code"] == "promo")
    await client_base.set_client_tag(session, 1, акция["id"], True, "Виктор")

    задача = (await client_base.get_tasks(session))[0]
    assert задача["script_source"] == "default"
    # Для потерянных это ветки регламента: начало, причины ухода, завершение.
    коды = [в["variant"] for в in задача["scripts"]]
    assert коды[0] == "start" and "conflict" in коды and коды[-1] == "finish"
    assert задача["scripts"][0]["phone"].startswith("Здравствуйте, Пётр!")
    assert "Зафиксируйте детали" in next(
        в["hint"] for в in задача["scripts"] if в["variant"] == "quality")

    # Свой текст на ветку регламента перекрывает стандартный.
    await client_base.save_script(session, "group", "lost", "Свой текст для {имя}", None,
                                  "Игорь", variant="start")
    задача = (await client_base.get_tasks(session))[0]
    assert задача["scripts"][0]["phone"] == "Свой текст для Пётр"
    assert задача["script_source"] == "group"

    # Скрипт тега идёт впереди групповых.
    await client_base.save_script(session, "tag", "promo", "Акция для {имя}", None,
                                  "Игорь", variant="promo1", title="Праздник")
    задача = (await client_base.get_tasks(session))[0]
    assert задача["scripts"][0]["title"] == "Праздник"
    assert задача["phone_script"] == "Акция для Пётр"
    assert задача["script_source"] == "tag:promo"


@pytest.mark.asyncio
async def test_плановый_перезвон_поднимает_клиента_наверх(session):
    await _клиент(session, 1, сегмент="due", имя="Сегодня")
    await _клиент(session, 2, сегмент="lost", имя="Потом")
    await _клиент(session, 3, сегмент="lost", имя="Просто потерянный")
    сегодня = client_base.moscow_today()

    await client_base.set_next_contact(session, 1, сегодня, "обещал перезвонить", "Виктор")
    await client_base.set_next_contact(session, 2, сегодня + timedelta(days=5), None, "Виктор")

    очередь = await client_base.get_tasks(session)
    assert [t["client_name"] for t in очередь] == ["Сегодня", "Просто потерянный", "Потом"]
    assert очередь[0]["callback_due"] is True
    assert очередь[0]["next_contact_note"] == "обещал перезвонить"
    assert очередь[2]["callback_due"] is False

    # Отмена плана возвращает обычный порядок по важности сегмента.
    await client_base.set_next_contact(session, 1, None, None, "Виктор")
    assert [t["client_name"] for t in await client_base.get_tasks(session)][0] == "Просто потерянный"


@pytest.mark.asyncio
async def test_счётчик_контактов_считает_звонки_и_записи(session):
    задача = await _клиент(session, 1, имя="Частый")
    for исход in ("no_answer", "no_booking", "booked"):
        session.add(ContactAttempt(task_id=задача, outcome=исход, channel="phone",
                                   actor_id="Виктор", created_at=datetime.now(MOSCOW)))
    # Звонок двухлетней давности в годовой счётчик не попадает.
    session.add(ContactAttempt(task_id=задача, outcome="no_booking", channel="phone",
                               actor_id="Виктор", created_at=datetime.now(MOSCOW) - timedelta(days=800)))
    await session.commit()

    строка = (await client_base.get_tasks(session))[0]
    assert строка["contacts"] == {"total": 4, "year": 3, "booked": 1}


@pytest.mark.asyncio
async def test_на_сервер_уходят_только_id_и_цифры(session):
    """Обещание владельцу: имени и телефона в документе для сервера нет."""
    задача = await _клиент(session, 1, имя="Иван Иванов")
    session.add(ContactAttempt(task_id=задача, outcome="booked", channel="phone",
                               actor_id="Виктор", was_lost=True, verification_status="pending",
                               created_at=datetime.now(MOSCOW)))
    await session.commit()

    документы = await hub._обзвон_в_документы(session, date.today())
    записи = [з for месяц in документы.values() for з in месяц]
    assert len(записи) == 1
    assert set(записи[0]) == set(hub.ПОЛЯ_ЗВОНКА)
    assert записи[0]["yclients_id"] == 1001
    текст = str(документы)
    assert "Иван Иванов" not in текст and "+7999" not in текст


@pytest.mark.asyncio
async def test_вкладка_обзвонов_делит_по_результату(session):
    задача1 = await _клиент(session, 1, имя="Записался")
    задача2 = await _клиент(session, 2, имя="Отказался")
    await _клиент(session, 3, имя="Переехал")
    теги = await client_base.tags_list(session)
    await client_base.set_client_tag(session, 3, next(t for t in теги if t["code"] == "moved")["id"], True, "Виктор")
    await client_base.set_next_contact(session, 2, client_base.moscow_today() + timedelta(days=3), None, "Виктор")
    for задача, исход in ((задача1, "booked"), (задача2, "no_booking")):
        session.add(ContactAttempt(task_id=задача, outcome=исход, channel="phone",
                                   actor_id="Виктор", created_at=datetime.now(MOSCOW)))
    await session.commit()

    фид = await client_base.calls_feed(session, "month")
    группы = {г["code"]: г for г in фид["groups"]}
    assert [i["name"] for i in группы["booked"]["items"]] == ["Записался"]
    assert [i["name"] for i in группы["no_booking"]["items"]] == ["Отказался"]
    assert группы["no_answer"]["items"] == []
    assert группы["callback"]["items"] == []  # исход «перезвонить» — своя подгруппа
    assert [i["name"] for i in группы["planned"]["items"]] == ["Отказался"]
    assert [(i["name"], i["reason"]) for i in группы["excluded"]["items"]] == [("Переехал", "Переехал")]
    assert фид["by_admin"] == [{"name": "Виктор", "total": 2}]


@pytest.mark.asyncio
async def test_не_дозвонились_ставит_завтра_а_перезвонить_требует_дату(session):
    """Правила статусов владельца (16.10.2026)."""
    from datetime import timedelta as _td

    задача1 = await _клиент(session, 1, имя="Молчит")
    задача2 = await _клиент(session, 2, имя="Просил позже")
    сегодня = client_base.moscow_today()

    await client_base.record_outcome(session, задача1, "no_answer", "phone", None, "Виктор")
    клиент = await session.get(Client, 1)
    assert клиент.call_status == "no_answer"
    assert клиент.next_contact_at == сегодня + _td(days=1)
    assert клиент.last_call_by == "Виктор"
    # Разговора не было — дату последнего звонка не ставим.
    assert клиент.last_call_at is None

    # «Перезвонить» без даты не принимается.
    отказ = await client_base.record_outcome(session, задача2, "callback", "phone", None, "Виктор")
    assert отказ["ok"] is False and "дата" in отказ["error"].lower()
    ок = await client_base.record_outcome(session, задача2, "callback", "phone", "после отпуска",
                                          "Виктор", next_contact=сегодня + _td(days=10))
    assert ок["ok"] is True
    второй = await session.get(Client, 2)
    assert второй.next_contact_at == сегодня + _td(days=10)
    assert второй.next_contact_note == "после отпуска"


@pytest.mark.asyncio
async def test_светофор_ставится_и_гасится(session):
    await _клиент(session, 1, имя="Ворчун")
    assert (await client_base.set_loyalty(session, 1, "red", "Виктор"))["loyalty"] == "red"
    строка = (await client_base.get_tasks(session))[0]
    assert строка["loyalty"] == "red"
    # Повторное нажатие той же лампочки гасит светофор.
    assert (await client_base.set_loyalty(session, 1, "red", "Виктор"))["loyalty"] is None
    assert (await client_base.set_loyalty(session, 1, "синий", "Виктор"))["ok"] is False


@pytest.mark.asyncio
async def test_состояние_клиентов_уходит_на_сервер_без_имён(session):
    await _клиент(session, 1, имя="Иван Иванов")
    теги = await client_base.tags_list(session)
    await client_base.set_client_tag(session, 1, теги[0]["id"], True, "Виктор")
    await client_base.set_loyalty(session, 1, "green", "Виктор")
    await client_base.set_next_contact(session, 1, client_base.moscow_today(), "обещал", "Виктор")

    строки = await hub._состояние_клиентов(session)
    assert len(строки) == 1
    assert set(строки[0]) == set(hub.ПОЛЯ_СОСТОЯНИЯ)
    assert строки[0]["yclients_id"] == 1001 and строки[0]["loyalty"] == "green"
    assert строки[0]["tags"] == [теги[0]["code"]]
    # Ни имени, ни телефона, ни текста договорённости.
    текст = str(строки)
    assert "Иван Иванов" not in текст and "+7999" not in текст and "обещал" not in текст


@pytest.mark.asyncio
async def test_перезвонить_не_теряется_ни_в_очереди_ни_в_обзвонах(session):
    """Жалоба владельца 16.10.2026: нажал «Перезвонить» — клиент исчез."""
    from datetime import timedelta as _td

    задача = await _клиент(session, 1, имя="Иван")
    итог = await client_base.record_outcome(
        session, задача, "callback", "phone", "через 3 дня", "Виктор",
        next_contact=client_base.moscow_today() + _td(days=3))
    assert итог["ok"] is True

    очередь = await client_base.get_tasks(session)
    строка = next(t for t in очередь if t["client_name"] == "Иван")
    assert строка["call_status"] == "callback" and строка["called_today"] is True

    группы = {г["code"]: г for г in (await client_base.calls_feed(session, "month"))["groups"]}
    assert [i["name"] for i in группы["callback"]["items"]] == ["Иван"]
    assert группы["no_booking"]["items"] == []  # раньше попадал сюда
