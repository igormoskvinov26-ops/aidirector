"""План-факт должен считать всё заработанное, а не только барберов.

Владелец нашёл в реальном отчёте YCLIENTS продажу товара администратором
(Виктор, не входит в settings.barber_payroll_rules) и спросил, учитывает ли
её План-факт. Проверяется не предположение, а факт: _month_services и
_month_products (из них считается fact.earned_total) суммируют Visit и Sale
без всякого фильтра по сотруднику — в отличие от app/services/barber_month.py,
который живьём тянет из YCLIENTS только трёх зарегистрированных барберов.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base
from app.models.models import Client, Employee, Sale, Visit
from app.services.finance import _month_products, _month_services, get_plan_fact


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_month_totals_include_non_barber_employee(session: AsyncSession):
    barber_ids = {int(r["staff_id"]) for r in settings.barber_payroll_rules}
    assert 999999 not in barber_ids, "тестовый id должен быть заведомо не барбером"

    admin = Employee(id=1, yclients_id=999999, name="Виктор")
    client = Client(id=1, yclients_id=1, name="Тестовый клиент", phone="+70000000000")
    session.add_all([admin, client])
    await session.flush()

    today = datetime.now(UTC)
    session.add(Visit(
        id=1, yclients_id=1, client_id=client.id, employee_id=admin.id,
        datetime=today, status="completed", total_amount=Decimal("0"),
    ))
    session.add(Sale(
        id=1, yclients_id=1, employee_id=admin.id,
        datetime=today, total_amount=Decimal("1300"),
    ))
    await session.commit()

    month_start = today.date().replace(day=1)
    services = await _month_services(session, month_start, today.date())
    products = await _month_products(session, month_start, today.date())

    # Продажа администратора — 1300 ₽ — обязана попасть в месячную сумму,
    # хотя Виктор не входит ни в один payroll rule.
    assert products["amount"] == Decimal("1300")

    plan_fact = await get_plan_fact(session)
    assert plan_fact["fact"]["earned_total"] == float(services["amount"] + Decimal("1300"))
    assert plan_fact["fact"]["products_amount"] == 1300.0
