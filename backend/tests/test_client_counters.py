"""Два счётчика на всю базу, независимо от мастера — решение владельца
18.09.2026: «Повторные» (клиенты с 2+ завершёнными визитами, счётчик растёт
однократно на втором визите) и «Потерянные» (последний визит или запись
старше 60 дней; будущая запись снимает статус).
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.models import Client, Employee, Visit
from app.services.finance import get_repeat_and_lost_clients

МАСТЕР = 1


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def _seed(session: AsyncSession, clients: int) -> None:
    session.add(Employee(id=МАСТЕР, yclients_id=999, name="Мастер"))
    for i in range(1, clients + 1):
        session.add(Client(id=i, yclients_id=i, name=f"Клиент {i}", phone=f"+7999000{i:04d}"))
    await session.flush()


async def _visit(
    session: AsyncSession, id_: int, client_id: int, days_ago: int, status: str = "completed",
) -> None:
    session.add(Visit(
        id=id_, yclients_id=id_, client_id=client_id, employee_id=МАСТЕР,
        datetime=datetime.now(UTC) - timedelta(days=days_ago),
        status=status, total_amount=Decimal("1000"),
    ))


@pytest.mark.asyncio
async def test_второй_визит_увеличивает_повторных(session: AsyncSession):
    await _seed(session, clients=1)
    await _visit(session, 1, 1, days_ago=200)
    await _visit(session, 2, 1, days_ago=5)
    await session.commit()

    итог = await get_repeat_and_lost_clients(session)
    assert итог["repeat_clients"] == 1


@pytest.mark.asyncio
async def test_один_визит_не_повторный(session: AsyncSession):
    await _seed(session, clients=1)
    await _visit(session, 1, 1, days_ago=10)
    await session.commit()

    итог = await get_repeat_and_lost_clients(session)
    assert итог["repeat_clients"] == 0


@pytest.mark.asyncio
async def test_последний_визит_больше_60_дней_назад_это_потерянный(session: AsyncSession):
    await _seed(session, clients=1)
    await _visit(session, 1, 1, days_ago=61)
    await session.commit()

    итог = await get_repeat_and_lost_clients(session)
    assert итог["lost_clients"] == 1


@pytest.mark.asyncio
async def test_визит_в_пределах_60_дней_не_потерянный(session: AsyncSession):
    await _seed(session, clients=1)
    await _visit(session, 1, 1, days_ago=59)
    await session.commit()

    итог = await get_repeat_and_lost_clients(session)
    assert итог["lost_clients"] == 0


@pytest.mark.asyncio
async def test_будущая_запись_снимает_статус_потерянного(session: AsyncSession):
    await _seed(session, clients=1)
    await _visit(session, 1, 1, days_ago=200, status="completed")
    await _visit(session, 2, 1, days_ago=-14, status="scheduled")
    await session.commit()

    итог = await get_repeat_and_lost_clients(session)
    assert итог["lost_clients"] == 0


@pytest.mark.asyncio
async def test_только_будущая_запись_без_завершённого_визита_не_считается(session: AsyncSession):
    """Клиент записался, но ни разу не приходил — это ещё не «его клиент»."""
    await _seed(session, clients=1)
    await _visit(session, 1, 1, days_ago=-3, status="scheduled")
    await session.commit()

    итог = await get_repeat_and_lost_clients(session)
    assert итог["repeat_clients"] == 0
    assert итог["lost_clients"] == 0


@pytest.mark.asyncio
async def test_несколько_клиентов_считаются_независимо(session: AsyncSession):
    await _seed(session, clients=3)
    # Клиент 1: повторный, не потерянный.
    await _visit(session, 1, 1, days_ago=100)
    await _visit(session, 2, 1, days_ago=5)
    # Клиент 2: один визит давно — потерянный.
    await _visit(session, 3, 2, days_ago=70)
    # Клиент 3: один визит недавно — ни то ни другое.
    await _visit(session, 4, 3, days_ago=5)
    await session.commit()

    итог = await get_repeat_and_lost_clients(session)
    assert итог == {"repeat_clients": 1, "lost_clients": 1}
