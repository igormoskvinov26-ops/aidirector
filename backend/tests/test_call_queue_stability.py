"""Критический баг из прода (решение владельца 22.11.2026): раньше каждый
цикл синхронизации (весь день, каждые несколько минут) refresh_tasks()
удалял ВСЕ открытые задачи обзвона и заводил их заново — даже тем, у кого
сегмент не изменился. Админ, открывший список утром и работающий с ним,
через несколько минут отмечал результат по уже несуществующему task_id:
ответ тихо терялся (клиент не попадал в журнал), а в худшем случае id мог
к этому моменту относиться к другому клиенту.

Здесь закреплено два независимых слоя защиты:
  1. refresh_tasks() больше не трогает задачи тех, чей сегмент не изменился —
     id стабилен весь день, гонки почти не остаётся;
  2. record_outcome() сверяет client_id, который реально видел админ, с тем,
     что сейчас в задаче — и отказывает, а не пишет не тому в журнал,
     если расхождение всё же произошло.
"""

from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.models import Client, ContactAttempt, ContactTask
from app.services import call_journal, client_base

СЕГОДНЯ = date.today()


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


@pytest.fixture(autouse=True)
def journal_dir(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "output_dir", tmp_path)
    return tmp_path


def _профили(карта: dict) -> callable:
    async def профили(_session):
        return карта
    return профили


@pytest.mark.asyncio
async def test_id_задачи_стабилен_если_сегмент_не_изменился(session, monkeypatch):
    session.add(Client(id=1, yclients_id=1001, name="Анна", phone="+70001"))
    await session.commit()
    monkeypatch.setattr(client_base, "build_client_profiles", _профили({1: {"segment": "risk"}}))

    итог1 = await client_base.refresh_tasks(session)
    задача = (await session.execute(select(ContactTask))).scalars().one()
    assert итог1["tasks_created"] == 1 and задача.client_id == 1

    # Второй цикл синхронизации — ничего не поменялось у клиента.
    итог2 = await client_base.refresh_tasks(session)
    assert итог2 == {"tasks_created": 0, "tasks_removed": 0, "date": СЕГОДНЯ.isoformat()}
    та_же_задача = (await session.execute(select(ContactTask))).scalars().one()
    assert та_же_задача.id == задача.id, "id задачи не должен меняться между циклами синхронизации"


@pytest.mark.asyncio
async def test_обновление_не_трогает_незатронутых_клиентов(session, monkeypatch):
    """Два клиента в очереди; у одного сегмент меняется, у другого — нет.
    Задача второго должна пережить пересборку с тем же id."""
    session.add(Client(id=1, yclients_id=1001, name="Анна", phone="+70001"))
    session.add(Client(id=2, yclients_id=1002, name="Борис", phone="+70002"))
    await session.commit()
    monkeypatch.setattr(
        client_base, "build_client_profiles",
        _профили({1: {"segment": "risk"}, 2: {"segment": "due"}}),
    )
    await client_base.refresh_tasks(session)
    задачи = {t.client_id: t.id for t in (await session.execute(select(ContactTask))).scalars().all()}
    id_бориса_до = задачи[2]

    # Анна выполнила визит и выпала из обзвона; Борис остался как был.
    monkeypatch.setattr(client_base, "build_client_profiles", _профили({2: {"segment": "due"}}))
    итог = await client_base.refresh_tasks(session)
    assert итог["tasks_removed"] == 1 and итог["tasks_created"] == 0

    оставшиеся = (await session.execute(select(ContactTask))).scalars().all()
    assert len(оставшиеся) == 1
    assert оставшиеся[0].client_id == 2
    assert оставшиеся[0].id == id_бориса_до, "задача Бориса не должна была пересоздаваться"


@pytest.mark.asyncio
async def test_новый_клиент_в_сегменте_получает_новую_задачу(session, monkeypatch):
    session.add(Client(id=1, yclients_id=1001, name="Анна", phone="+70001"))
    await session.commit()
    monkeypatch.setattr(client_base, "build_client_profiles", _профили({1: {"segment": "risk"}}))
    await client_base.refresh_tasks(session)

    session.add(Client(id=2, yclients_id=1002, name="Борис", phone="+70002"))
    await session.commit()
    monkeypatch.setattr(
        client_base, "build_client_profiles",
        _профили({1: {"segment": "risk"}, 2: {"segment": "late"}}),
    )
    итог = await client_base.refresh_tasks(session)
    assert итог == {"tasks_created": 1, "tasks_removed": 0, "date": СЕГОДНЯ.isoformat()}


@pytest.mark.asyncio
async def test_устаревший_task_id_после_пересборки_не_пишет_чужому_клиенту(session, monkeypatch):
    """Воспроизводит сам инцидент: админ открыл карточку Анны, за это время
    прошёл цикл синхронизации, Анна перестала быть актуальной (её задача
    удалена), а на её место пришёл Борис. В SQLite (как и в тестах) id
    освобождённой строки тут же переиспользуется для новой — ровно то, что,
    видимо, и происходило в проде. Отметка по старому task_id не должна
    тихо записаться в журнал не того клиента: expected_client_id обязан
    поймать расхождение."""
    session.add(Client(id=1, yclients_id=1001, name="Анна", phone="+70001"))
    await session.commit()
    monkeypatch.setattr(client_base, "build_client_profiles", _профили({1: {"segment": "risk"}}))
    await client_base.refresh_tasks(session)
    задача_анны = (await session.execute(select(ContactTask))).scalars().one()
    id_задачи_анны = задача_анны.id

    session.add(Client(id=2, yclients_id=1002, name="Борис", phone="+70002"))
    await session.commit()
    monkeypatch.setattr(client_base, "build_client_profiles", _профили({2: {"segment": "risk"}}))
    await client_base.refresh_tasks(session)

    # Админ всё ещё держит на экране старую карточку Анны и жмёт «Записался».
    result = await client_base.record_outcome(
        session, id_задачи_анны, "booked", "phone", None, "Катя", expected_client_id=1,
    )
    assert result["ok"] is False and "mismatch" in result["error"]
    assert (await session.execute(select(ContactAttempt))).scalars().all() == []
    assert not call_journal.journal_path().exists()


@pytest.mark.asyncio
async def test_несовпадение_клиента_отклоняется_и_ничего_не_пишет(session):
    """Прямая проверка второго слоя защиты: если задача сейчас указывает не
    на того клиента, которого видел админ, — запись отклоняется."""
    session.add(Client(id=1, yclients_id=1001, name="Анна", phone="+70001"))
    session.add(Client(id=2, yclients_id=1002, name="Борис", phone="+70002"))
    await session.flush()
    session.add(ContactTask(id=99, client_id=2, group_code="risk", priority=1,
                            due_date=СЕГОДНЯ, status="open"))
    await session.commit()

    # Админ на экране видел Анну (id=1), но задача 99 сейчас — Бориса (id=2).
    result = await client_base.record_outcome(
        session, 99, "booked", "phone", None, "Катя", expected_client_id=1,
    )
    assert result["ok"] is False and "mismatch" in result["error"]
    assert (await session.execute(select(ContactAttempt))).scalars().all() == []
    задача = await session.get(ContactTask, 99)
    assert задача.status == "open", "задачу нельзя помечать выполненной при отклонённой записи"
    assert not call_journal.journal_path().exists()


@pytest.mark.asyncio
async def test_без_expected_client_id_поведение_прежнее(session):
    """Обратная совместимость: внутренние/старые вызовы без client_id
    по-прежнему работают — проверка просто пропускается."""
    session.add(Client(id=1, yclients_id=1001, name="Анна", phone="+70001"))
    await session.flush()
    session.add(ContactTask(id=5, client_id=1, group_code="risk", priority=1,
                            due_date=СЕГОДНЯ, status="open"))
    await session.commit()

    result = await client_base.record_outcome(session, 5, "booked", "phone", None, "Катя")
    assert result["ok"] is True
    assert (await session.execute(select(ContactAttempt))).scalars().one().task_id == 5
