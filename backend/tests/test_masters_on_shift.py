"""Сколько мастеров на смене в План-факте — тот же состав, что в «Смене».

Жалоба владельца 25.11.2026: блок «Сегодня» показывал троих, хотя на смене
было больше, — туда попадали только мастера с уже закрытыми записями. Мастер
на смене без закрытых записей выпадал вместе со своим гарантом.
"""

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.models import Base, Client, Employee, Shift, ShiftEmployee, Visit
from app.services import finance


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


async def _салон(session):
    """Четыре мастера; YCLIENTS staff_id = 10 + номер."""
    c = Client(yclients_id=1, name="К", phone="+79990000000")
    session.add(c)
    мастера = [Employee(yclients_id=10 + i, name=имя)
               for i, имя in enumerate(("Дмитрий", "Арташ", "Ксения", "Дарья"), start=1)]
    session.add_all(мастера)
    await session.flush()
    return c, мастера


def _визит(c, e, n, статус, сумма=1000):
    return Visit(yclients_id=1000 + n, client_id=c.id, employee_id=e.id,
                 datetime=datetime.now(UTC), total_amount=сумма, status=статус)


@pytest.mark.asyncio
async def test_мастер_на_смене_без_закрытых_записей_в_составе(session):
    c, (дм, ар, кс, да) = await _салон(session)
    session.add_all([_визит(c, дм, 1, "completed", 7340), _визит(c, ар, 2, "completed", 2430),
                     _визит(c, кс, 3, "completed", 900), _визит(c, да, 4, "scheduled", 2000)])
    день = datetime.now(UTC).date()
    смена = Shift(shift_date=день)
    session.add(смена)
    await session.flush()
    for e in (дм, ар, кс, да):
        session.add(ShiftEmployee(shift_id=смена.id, staff_id=e.yclients_id,
                                  staff_name_snapshot=e.name))
    await session.commit()

    состав = await finance._today_by_master(session, день)
    assert sorted(m["name"] for m in состав) == ["Арташ", "Дарья", "Дмитрий", "Ксения"]
    assert next(m for m in состав if m["name"] == "Дарья")["services"] == 0
    assert await finance._get_masters_count(session, день) == 4


@pytest.mark.asyncio
async def test_без_открытой_смены_считаются_мастера_с_записями_кроме_отменённых(session):
    c, (дм, ар, кс, да) = await _салон(session)
    session.add_all([_визит(c, дм, 1, "completed"), _визит(c, ар, 2, "scheduled"),
                     _визит(c, кс, 3, "cancelled"), _визит(c, да, 4, "no_show")])
    await session.commit()
    день = datetime.now(UTC).date()

    assert sorted(m["name"] for m in await finance._today_by_master(session, day=день)) == [
        "Арташ", "Дмитрий"]
    assert await finance._get_masters_count(session, день) == 2


@pytest.mark.asyncio
async def test_работавший_мастер_не_выпадает_если_его_нет_в_составе_смены(session):
    c, (дм, ар, кс, да) = await _салон(session)
    session.add_all([_визит(c, дм, 1, "completed"), _визит(c, кс, 2, "completed")])
    день = datetime.now(UTC).date()
    смена = Shift(shift_date=день)
    session.add(смена)
    await session.flush()
    session.add(ShiftEmployee(shift_id=смена.id, staff_id=дм.yclients_id,
                              staff_name_snapshot="Дмитрий"))
    await session.commit()

    assert sorted(m["name"] for m in await finance._today_by_master(session, день)) == [
        "Дмитрий", "Ксения"]
