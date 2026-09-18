"""Возвращаемость мастера: доля клиентов, пришедших к нему повторно, и
сколько из них уже потерянные.

Решение владельца 18.09.2026: возврат — второй и любой следующий завершённый
визит к тому же самому мастеру, без ограничения по срокам между визитами.
Клиент, сходивший раз к одному мастеру и раз к другому, — не вернулся ни к
одному из них.

Потерянный (уточнено в том же разговоре) — из клиентов мастера тот, чей
последний визит или запись к нему старше LOST_AFTER_DAYS (60) дней. Будущая
запись снимает статус, даже если предыдущий визит был давно.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base
from app.models.models import Client, Employee, Visit
from app.services.finance import get_return_rate

КСЕНИЯ = 5659614  # settings.barber_payroll_rules по умолчанию (config.py)
АРТАШ = 5659611


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def _seed(session: AsyncSession, employees: list[tuple[int, int]], clients: int) -> None:
    """employees — [(local_id, yclients_id), ...]."""
    for local_id, yid in employees:
        session.add(Employee(id=local_id, yclients_id=yid, name=f"#{yid}"))
    for i in range(1, clients + 1):
        session.add(Client(id=i, yclients_id=i, name=f"Клиент {i}", phone=f"+7999000{i:04d}"))
    await session.flush()


async def _visit(
    session: AsyncSession, id_: int, employee_id: int, client_id: int,
    days_ago: int, status: str = "completed",
) -> None:
    session.add(Visit(
        id=id_, yclients_id=id_, client_id=client_id, employee_id=employee_id,
        datetime=datetime.now(UTC) - timedelta(days=days_ago),
        status=status, total_amount=Decimal("1000"),
    ))


@pytest.mark.asyncio
async def test_второй_визит_к_тому_же_мастеру_это_возврат(session: AsyncSession):
    await _seed(session, [(1, КСЕНИЯ)], clients=1)
    await _visit(session, 1, 1, 1, days_ago=300)
    await _visit(session, 2, 1, 1, days_ago=5)  # тот же клиент, тот же мастер, спустя почти год
    await session.commit()

    итог = await get_return_rate(session)
    ксения = next(m for m in итог["masters"] if m["staff_id"] == КСЕНИЯ)
    assert ксения["clients_total"] == 1
    assert ксения["clients_returned"] == 1
    assert ксения["return_rate_pct"] == 100.0


@pytest.mark.asyncio
async def test_визиты_к_разным_мастерам_не_считаются_возвратом(session: AsyncSession):
    """Один визит к Ксении, один — к Арташу. Клиент не вернулся ни к одной."""
    await _seed(session, [(1, КСЕНИЯ), (2, АРТАШ)], clients=1)
    await _visit(session, 1, 1, 1, days_ago=10)
    await _visit(session, 2, 2, 1, days_ago=5)
    await session.commit()

    итог = await get_return_rate(session)
    ксения = next(m for m in итог["masters"] if m["staff_id"] == КСЕНИЯ)
    арташ = next(m for m in итог["masters"] if m["staff_id"] == АРТАШ)
    assert ксения == {
        "staff_id": КСЕНИЯ, "name": ксения["name"],
        "clients_total": 1, "clients_returned": 0, "clients_lost": 0,
        "return_rate_pct": 0.0,
    }
    assert арташ["clients_returned"] == 0


@pytest.mark.asyncio
async def test_незавершённые_визиты_не_считаются(session: AsyncSession):
    """Отменённый, неявка и будущая запись — не факт, что клиент вообще был."""
    await _seed(session, [(1, КСЕНИЯ)], clients=1)
    await _visit(session, 1, 1, 1, days_ago=10, status="completed")
    await _visit(session, 2, 1, 1, days_ago=5, status="cancelled")
    await _visit(session, 3, 1, 1, days_ago=4, status="no_show")
    await _visit(session, 4, 1, 1, days_ago=-3, status="scheduled")  # в будущем
    await session.commit()

    итог = await get_return_rate(session)
    ксения = next(m for m in итог["masters"] if m["staff_id"] == КСЕНИЯ)
    # Только один по-настоящему завершённый визит — клиент не «вернулся».
    assert ксения["clients_total"] == 1
    assert ксения["clients_returned"] == 0


@pytest.mark.asyncio
async def test_без_клиентов_процент_не_ноль_а_неизвестен(session: AsyncSession):
    """0 из 0 — это «нет данных», а не «0% возвращаемости»: разные вещи."""
    await _seed(session, [(1, КСЕНИЯ)], clients=0)
    await session.commit()

    итог = await get_return_rate(session)
    ксения = next(m for m in итог["masters"] if m["staff_id"] == КСЕНИЯ)
    assert ксения["clients_total"] == 0
    assert ксения["return_rate_pct"] is None


@pytest.mark.asyncio
async def test_сортировка_по_возвращаемости_лучшие_первыми(session: AsyncSession):
    await _seed(session, [(1, КСЕНИЯ), (2, АРТАШ)], clients=4)
    # Ксения: 2 клиента, оба вернулись — 100%.
    await _visit(session, 1, 1, 1, days_ago=100)
    await _visit(session, 2, 1, 1, days_ago=10)
    await _visit(session, 3, 1, 2, days_ago=100)
    await _visit(session, 4, 1, 2, days_ago=10)
    # Арташ: 2 клиента, ни один не вернулся — 0%.
    await _visit(session, 5, 2, 3, days_ago=50)
    await _visit(session, 6, 2, 4, days_ago=50)
    await session.commit()

    итог = await get_return_rate(session)
    порядок = [m["staff_id"] for m in итог["masters"] if m["staff_id"] in (КСЕНИЯ, АРТАШ)]
    assert порядок.index(КСЕНИЯ) < порядок.index(АРТАШ)


@pytest.mark.asyncio
async def test_все_настроенные_барберы_присутствуют_даже_без_визитов(session: AsyncSession):
    """Дмитрия в базе нет вовсе — он всё равно должен быть в списке, с None."""
    await _seed(session, [(1, КСЕНИЯ)], clients=1)
    await _visit(session, 1, 1, 1, days_ago=10)
    await session.commit()

    итог = await get_return_rate(session)
    имена = {m["staff_id"] for m in итог["masters"]}
    ожидается = {int(r["staff_id"]) for r in settings.barber_payroll_rules}
    assert имена == ожидается


# --------------------------------------------------------------------------- #
# Потерянные: последний визит/запись к мастеру старше 60 дней
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_последний_визит_больше_60_дней_назад_это_потерянный(session: AsyncSession):
    await _seed(session, [(1, КСЕНИЯ)], clients=1)
    await _visit(session, 1, 1, 1, days_ago=90)
    await session.commit()

    итог = await get_return_rate(session)
    ксения = next(m for m in итог["masters"] if m["staff_id"] == КСЕНИЯ)
    assert ксения["clients_lost"] == 1


@pytest.mark.asyncio
async def test_визит_в_пределах_60_дней_не_потерянный(session: AsyncSession):
    await _seed(session, [(1, КСЕНИЯ)], clients=1)
    await _visit(session, 1, 1, 1, days_ago=30)
    await session.commit()

    итог = await get_return_rate(session)
    ксения = next(m for m in итог["masters"] if m["staff_id"] == КСЕНИЯ)
    assert ксения["clients_lost"] == 0


@pytest.mark.asyncio
async def test_будущая_запись_снимает_статус_потерянного(session: AsyncSession):
    """Последний визит был давно, но на следующей неделе уже есть запись —
    клиент не потерян, он возвращается."""
    await _seed(session, [(1, КСЕНИЯ)], clients=1)
    await _visit(session, 1, 1, 1, days_ago=200, status="completed")
    await _visit(session, 2, 1, 1, days_ago=-7, status="scheduled")  # через неделю
    await session.commit()

    итог = await get_return_rate(session)
    ксения = next(m for m in итог["masters"] if m["staff_id"] == КСЕНИЯ)
    assert ксения["clients_lost"] == 0


@pytest.mark.asyncio
async def test_потерянные_считаются_в_разрезе_мастера(session: AsyncSession):
    """Клиент потерян для Ксении, но не для Арташа — у него был недавно."""
    await _seed(session, [(1, КСЕНИЯ), (2, АРТАШ)], clients=1)
    await _visit(session, 1, 1, 1, days_ago=100)
    await _visit(session, 2, 2, 1, days_ago=10)
    await session.commit()

    итог = await get_return_rate(session)
    ксения = next(m for m in итог["masters"] if m["staff_id"] == КСЕНИЯ)
    арташ = next(m for m in итог["masters"] if m["staff_id"] == АРТАШ)
    assert ксения["clients_lost"] == 1
    assert арташ["clients_lost"] == 0
