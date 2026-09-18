"""Заметка администратора на карточке клиента.

Единственное, ради чего она вообще нужна отдельной колонкой на клиенте, а не
полем на задаче обзвона: задачи пересобираются заново каждый день
(refresh_tasks удаляет все открытые и создаёт новые), а «перезвонить
завтра», написанное сегодня, должно назавтра снова оказаться на карточке
того же клиента.
"""

from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.models import Client, ContactTask
from app.services.client_base import get_tasks, set_admin_note


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def _make_task(session: AsyncSession) -> tuple[int, int]:
    client = Client(id=1, yclients_id=1001, name="Иван Петров", phone="+79990000000")
    session.add(client)
    await session.flush()
    task = ContactTask(
        client_id=client.id,
        group_code="risk",
        priority=1,
        due_date=date.today(),
        status="open",
        script_version="v1",
    )
    session.add(task)
    await session.commit()
    return client.id, task.id


@pytest.mark.asyncio
async def test_note_saved_and_returned(session: AsyncSession):
    client_id, _task_id = await _make_task(session)
    result = await set_admin_note(session, client_id, "перезвонить завтра")
    assert result == {"ok": True, "client_id": client_id, "admin_note": "перезвонить завтра"}

    tasks = await get_tasks(session)
    assert tasks[0]["admin_note"] == "перезвонить завтра"


@pytest.mark.asyncio
async def test_note_survives_daily_task_regeneration(session: AsyncSession):
    """Ровно тот сценарий, ради которого заметка живёт на клиенте, а не на задаче."""
    client_id, task_id = await _make_task(session)
    await set_admin_note(session, client_id, "перезвонить завтра")

    # То, что делает refresh_tasks() каждый день: старая открытая задача
    # удаляется, для сегментированного клиента заводится новая — с другим id.
    old_task = await session.get(ContactTask, task_id)
    await session.delete(old_task)
    # Флашим удаление до вставки: иначе уникальный индекс (client_id,
    # group_code, due_date) видит старую строку ещё не удалённой и новую
    # вставку отвергает — ровно так, как в настоящем refresh_tasks() старая
    # задача уходит через Core-DELETE, выполняющийся немедленно, а не через
    # отложенный ORM-delete, как здесь.
    await session.flush()
    new_task = ContactTask(
        client_id=client_id,
        group_code="risk",
        priority=1,
        due_date=date.today(),
        status="open",
        script_version="v1",
    )
    session.add(new_task)
    await session.commit()
    # SQLite переиспользует id без AUTOINCREMENT — в бою (Postgres) id будет
    # другим, но для проверки это и не важно: важно, что задача — новая
    # строка, а заметка взята не из неё, а с клиента.
    assert new_task is not old_task

    tasks = await get_tasks(session)
    assert len(tasks) == 1
    assert tasks[0]["admin_note"] == "перезвонить завтра"


@pytest.mark.asyncio
async def test_blank_note_clears_it(session: AsyncSession):
    client_id, _task_id = await _make_task(session)
    await set_admin_note(session, client_id, "перезвонить завтра")
    result = await set_admin_note(session, client_id, "   ")
    assert result["admin_note"] is None

    tasks = await get_tasks(session)
    assert tasks[0]["admin_note"] is None


@pytest.mark.asyncio
async def test_note_for_unknown_client(session: AsyncSession):
    result = await set_admin_note(session, 999, "что угодно")
    assert result == {"ok": False, "error": "client not found"}
