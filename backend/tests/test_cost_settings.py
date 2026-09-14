"""Чтение и запись расходов — на настоящей базе.

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
    DEFAULT_FIXED_MONTHLY,
    _break_even_revenue,
    get_cost_settings,
    get_costs,
    set_cost_settings,
)

SAMPLE = {
    "fixed_monthly": 403149,
    "materials_pct": 3.5,
    "acquiring_pct": 0,
    "master_commission_pct": 40,
    "product_commission_pct": 10,
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
    assert saved["fixed_monthly"] == 403149
    assert saved["master_commission_pct"] == 40
    assert saved["is_default"] is False

    again = await get_cost_settings(session)
    assert again["fixed_monthly"] == 403149


@pytest.mark.asyncio
async def test_monthly_sum_is_spread_over_the_month(session):
    """Ровно то, о чём договорились: одно число, делённое на дни месяца."""
    await set_cost_settings(session, SAMPLE)
    settings = await get_cost_settings(session)
    costs = await get_costs(session)

    expected = Decimal("403149") / Decimal(settings["days_in_month"])
    assert abs(costs.fixed_daily - expected) < Decimal("0.02")
    assert settings["fixed_daily"] == float(round(expected, 2))


@pytest.mark.asyncio
async def test_raising_expenses_raises_the_threshold(session):
    """Смысл настройки: поднял расходы — порог поехал следом."""
    await set_cost_settings(session, SAMPLE)
    before = _break_even_revenue(2, await get_costs(session))

    await set_cost_settings(session, {**SAMPLE, "fixed_monthly": 500000})
    after = _break_even_revenue(2, await get_costs(session))

    assert after > before


@pytest.mark.asyncio
async def test_master_pay_is_not_part_of_the_fixed_sum(session):
    """Оплата мастеров считается процентом и в постоянную сумму не входит.

    Попади она ещё и туда — учлась бы дважды, и порог ушёл бы вверх на ровном
    месте. Постоянный расход в день обязан зависеть только от своей суммы.
    """
    await set_cost_settings(session, SAMPLE)
    base = (await get_costs(session)).fixed_daily

    await set_cost_settings(session, {**SAMPLE, "master_commission_pct": 55})
    assert (await get_costs(session)).fixed_daily == base

    await set_cost_settings(session, {**SAMPLE, "materials_pct": 12})
    assert (await get_costs(session)).fixed_daily == base


@pytest.mark.asyncio
async def test_collapsing_the_breakdown_did_not_move_the_threshold(session):
    """Свёртка статей в одно число не должна была сдвинуть экономику.

    Раньше сумма складывалась из шести статей плюс администратор за смены:
    296 000 + 4 000 x 15,5 + 45 149. Теперь она задаётся одним числом, и оно
    обязано быть тем же.
    """
    assert DEFAULT_FIXED_MONTHLY == (
        Decimal("296000") + Decimal("4000") * Decimal("15.5") + Decimal("45149")
    )

    await set_cost_settings(session, SAMPLE)
    assert (await get_costs(session)).fixed_daily > 0


@pytest.mark.asyncio
async def test_second_save_updates_the_same_row(session):
    """Строка всегда одна: иначе настройки начали бы множиться."""
    await set_cost_settings(session, SAMPLE)
    await set_cost_settings(session, {**SAMPLE, "fixed_monthly": 1})
    settings = await get_cost_settings(session)
    assert settings["fixed_monthly"] == 1


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
