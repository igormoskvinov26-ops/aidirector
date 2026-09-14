"""Чтение и запись структуры расходов — на настоящей базе.

Берётся SQLite в памяти: задача не в том, чтобы повторить продакшн, а в том,
чтобы модель, запросы и пересчёт «в месяц → в день» проверялись против живой
базы, а не только на глаз.
"""

from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.models import CostModel  # noqa: F401  (регистрирует таблицу)
from app.services.finance import (
    DEFAULT_COSTS,
    _break_even_revenue,
    get_cost_settings,
    get_costs,
    set_cost_settings,
)

SAMPLE = {
    "rent_monthly": 170000,
    "utilities_monthly": 15000,
    "manager_monthly": 90000,
    "cleaning_monthly": 15000,
    "taxes_monthly": 6000,
    "other_fixed_monthly": 0,
    "admin_per_shift": 4000,
    "materials_pct": 3.5,
    "acquiring_pct": 0,
    "master_commission_pct": 40,
    "master_min_guarantee": 4000,
}


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
async def test_empty_table_falls_back_to_report_values(session):
    """Без настроек считаем по августовскому отчёту, а не по нулям.

    Нули обнулили бы порог безубыточности, и любой день выглядел бы прибыльным.
    """
    costs = await get_costs(session)
    assert costs == DEFAULT_COSTS
    assert costs.fixed_daily > 0


@pytest.mark.asyncio
async def test_saved_values_come_back(session):
    saved = await set_cost_settings(session, SAMPLE)
    assert saved["rent_monthly"] == 170000
    assert saved["master_commission_pct"] == 40
    assert saved["fixed_monthly_total"] == 296000
    assert saved["is_default"] is False

    again = await get_cost_settings(session)
    assert again["fixed_monthly_total"] == 296000


@pytest.mark.asyncio
async def test_monthly_sums_are_spread_over_the_month(session):
    await set_cost_settings(session, SAMPLE)
    settings = await get_cost_settings(session)
    costs = await get_costs(session)
    # Оклады делятся на дни месяца, оплата смены добавляется целиком.
    expected = Decimal("296000") / Decimal(settings["days_in_month"]) + Decimal("4000")
    assert abs(costs.fixed_daily - expected) < Decimal("0.02")


@pytest.mark.asyncio
async def test_raising_the_rent_raises_the_threshold(session):
    """Смысл настроек: изменил аренду — порог поехал следом."""
    await set_cost_settings(session, SAMPLE)
    before = _break_even_revenue(2, await get_costs(session))

    await set_cost_settings(session, {**SAMPLE, "rent_monthly": 250000})
    after = _break_even_revenue(2, await get_costs(session))

    assert after > before


@pytest.mark.asyncio
async def test_second_save_updates_the_same_row(session):
    """Строка всегда одна: иначе настройки начали бы множиться."""
    await set_cost_settings(session, SAMPLE)
    await set_cost_settings(session, {**SAMPLE, "rent_monthly": 1})
    settings = await get_cost_settings(session)
    assert settings["rent_monthly"] == 1


def test_impossible_economics_is_rejected():
    """Сумма переменных долей выше ста процентов не сохраняется.

    При таких условиях каждый заработанный рубль приносит убыток, порога
    безубыточности не существует, и график молча показал бы бессмыслицу.
    """
    from pydantic import ValidationError

    from app.schemas.schemas import CostSettingsRequest

    with pytest.raises(ValidationError):
        CostSettingsRequest(**{**SAMPLE, "master_commission_pct": 97})


def test_realistic_economics_is_accepted():
    from app.schemas.schemas import CostSettingsRequest

    assert CostSettingsRequest(**SAMPLE).master_commission_pct == 40
