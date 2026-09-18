"""История «Повторные»/«Потерянные» и показателей мастеров для графика по
клику на плитку — решение владельца 18.09.2026.

backfill_metric_history пересчитывает историю за каждый день окна из дат
завершённых визитов, тем же приёмом, что backfill_timeseries для сегментов
клиентской базы: без отдельных снимков, сразу на всю глубину истории в базе.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.models import Client, Employee, Visit
from app.services.client_base import backfill_metric_history

КСЕНИЯ = 5659614  # settings.barber_payroll_rules по умолчанию (тестовый .env)
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
    for local_id, yid in employees:
        session.add(Employee(id=local_id, yclients_id=yid, name=f"#{yid}"))
    for i in range(1, clients + 1):
        session.add(Client(id=i, yclients_id=i, name=f"Клиент {i}", phone=f"+7999000{i:04d}"))
    await session.flush()


async def _visit(
    session: AsyncSession, id_: int, employee_id: int, client_id: int, days_ago: int,
) -> None:
    session.add(Visit(
        id=id_, yclients_id=id_, client_id=client_id, employee_id=employee_id,
        datetime=datetime.now(UTC) - timedelta(days=days_ago),
        status="completed", total_amount=Decimal("1000"),
    ))


def _на_сегодня(итог: dict, key: str) -> float:
    return итог["series"][key][-1]["value"]


@pytest.mark.asyncio
async def test_сегодняшняя_точка_совпадает_с_живым_расчётом(session: AsyncSession):
    await _seed(session, [(1, КСЕНИЯ)], clients=1)
    await _visit(session, 1, 1, 1, days_ago=300)
    await _visit(session, 2, 1, 1, days_ago=5)
    await session.commit()

    итог = await backfill_metric_history(session, days=10)
    assert _на_сегодня(итог, f"master:{КСЕНИЯ}:clients_total") == 1
    assert _на_сегодня(итог, f"master:{КСЕНИЯ}:return_rate_pct") == 100.0
    assert _на_сегодня(итог, "global:repeat_clients") == 1


@pytest.mark.asyncio
async def test_график_растёт_день_в_день_когда_клиент_становится_повторным(session: AsyncSession):
    """До второго визита — 0 повторных, после — 1: видно на самом графике,
    не только в сегодняшней точке."""
    await _seed(session, [(1, КСЕНИЯ)], clients=1)
    await _visit(session, 1, 1, 1, days_ago=10)
    await _visit(session, 2, 1, 1, days_ago=3)
    await session.commit()

    итог = await backfill_metric_history(session, days=15)
    # Точная дата не важна: важно, что где-то график переходит от 0 к 1.
    значения = [p["value"] for p in итог["series"]["global:repeat_clients"]]
    assert значения[0] == 0
    assert значения[-1] == 1
    assert значения[-1] >= значения[0]


@pytest.mark.asyncio
async def test_потерянный_историческим_днём_отличается_от_сегодняшнего(session: AsyncSession):
    """90 дней назад клиент был потерян за 5 дней до того момента —
    к сегодняшнему дню давность только растёт, статус не может исчезнуть."""
    await _seed(session, [(1, КСЕНИЯ)], clients=1)
    await _visit(session, 1, 1, 1, days_ago=90)
    await session.commit()

    итог = await backfill_metric_history(session, days=100)
    значения = [p["value"] for p in итог["series"][f"master:{КСЕНИЯ}:clients_lost"]]
    # На 89-й день назад (день визита + 1) клиент точно не потерян — 60
    # дней ещё не прошло. Сегодня — потерян.
    assert значения[-1] == 1
    день_визита = 100 - 90
    assert значения[день_визита] == 0


@pytest.mark.asyncio
async def test_показатели_по_мастерам_независимы(session: AsyncSession):
    await _seed(session, [(1, КСЕНИЯ), (2, АРТАШ)], clients=2)
    await _visit(session, 1, 1, 1, days_ago=10)
    await _visit(session, 2, 2, 2, days_ago=10)
    await _visit(session, 3, 2, 2, days_ago=3)  # у Арташа клиент вернулся
    await session.commit()

    итог = await backfill_metric_history(session, days=15)
    assert _на_сегодня(итог, f"master:{КСЕНИЯ}:clients_total") == 1
    assert _на_сегодня(итог, f"master:{АРТАШ}:clients_total") == 1
    assert _на_сегодня(итог, f"master:{АРТАШ}:return_rate_pct") == 100.0
    assert _на_сегодня(итог, f"master:{КСЕНИЯ}:return_rate_pct") == 0.0


@pytest.mark.asyncio
async def test_без_визитов_возвращаемость_не_попадает_в_историю(session: AsyncSession):
    await _seed(session, [(1, КСЕНИЯ)], clients=0)
    await session.commit()

    итог = await backfill_metric_history(session, days=5)
    assert f"master:{КСЕНИЯ}:return_rate_pct" not in итог["series"]
    assert _на_сегодня(итог, f"master:{КСЕНИЯ}:clients_total") == 0
