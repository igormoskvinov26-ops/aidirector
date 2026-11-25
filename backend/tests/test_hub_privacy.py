"""На общий сервер (за рубежом) не уходят имена, телефоны и комментарии клиентов.

Требование владельца: персональные данные клиентов хранятся только на
компьютере салона. Тест собирает всё, что Пульт отправил бы на сервер, и
ищет в этом имя, телефон и текст комментария.
"""

import json

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.models import Client, ClientTag, ClientTagLink, ContactTask
from app.services import client_base, hub


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_на_сервер_не_уходят_имя_телефон_и_комментарий(session):
    session.add(Client(id=1, yclients_id=555001, name="Секретов Иван", phone="+7 (916) 123-45-67",
                       admin_note="ЛИЧНАЯ ЗАМЕТКА", loyalty="red"))
    session.add(ClientTag(id=1, code="vip", name="постоянный"))
    await session.flush()
    session.add(ClientTagLink(client_id=1, tag_id=1))
    task = ContactTask(client_id=1, group_code="lost", priority=5,
                       due_date=client_base.moscow_today(), status="open")
    session.add(task)
    await session.commit()
    await client_base.record_outcome(session, task.id, "booked", "phone", "КОММЕНТАРИЙ ЗВОНКА", "Аня", 1)

    отправка = json.dumps(await hub.локальные(session), ensure_ascii=False)

    assert "555001" in отправка  # звонок и состояние ушли — по номеру YCLIENTS
    for запрещено in ("Секретов", "Иван", "9161234567", "123-45-67", "ЛИЧНАЯ ЗАМЕТКА", "КОММЕНТАРИЙ ЗВОНКА"):
        assert запрещено not in отправка.replace(" ", "").replace("(", "").replace(")", "") \
            and запрещено not in отправка, f"на сервер уходит: {запрещено}"
