"""Арифметика безубыточности.

Проверяется не совпадение с заранее выписанными числами, а свойство: при
выручке, равной порогу, день выходит ровно в ноль. Такой тест переживёт
изменение аренды или процента мастеру — а именно эти числа и будут меняться.
"""

from decimal import Decimal

import pytest

from app.services.finance import (
    FIXED_DAILY_COST,
    MASTER_COMMISSION_PCT,
    MASTER_MIN_SALARY,
    VARIABLE_COST_PCT,
    Costs,
    _break_even_revenue,
    _compute_margin,
    _revenue_for_profit,
)


@pytest.mark.parametrize("masters", [1, 2, 3])
def test_break_even_revenue_zeroes_the_day(masters):
    """На пороге день не в минусе и не в плюсе."""
    revenue = _break_even_revenue(masters)
    margin = _compute_margin(revenue, masters)
    assert abs(margin["margin_rub"]) < Decimal("0.05")


@pytest.mark.parametrize("masters", [1, 2, 3])
def test_rouble_below_break_even_is_a_loss(masters):
    revenue = _break_even_revenue(masters) - Decimal("100")
    assert _compute_margin(revenue, masters)["margin_rub"] < 0


@pytest.mark.parametrize("masters", [1, 2, 3])
def test_rouble_above_break_even_is_a_profit(masters):
    revenue = _break_even_revenue(masters) + Decimal("100")
    assert _compute_margin(revenue, masters)["margin_rub"] > 0


def test_more_masters_need_more_revenue():
    """Каждый следующий человек на смене поднимает планку, а не опускает."""
    one, two, three = (_break_even_revenue(n) for n in (1, 2, 3))
    assert one < two < three


def test_zero_masters_treated_as_one():
    """День без единого мастера всё равно стоит денег: аренда не отменяется."""
    assert _break_even_revenue(0) == _break_even_revenue(1)
    assert _break_even_revenue(0) > FIXED_DAILY_COST


def test_guarantee_applies_on_a_quiet_day():
    """При низкой выручке мастер получает гарант, а не процент."""
    revenue = Decimal("5000")
    costs = _compute_margin(revenue, 1)["costs"]
    assert costs["master_commission"] == MASTER_MIN_SALARY
    assert revenue * MASTER_COMMISSION_PCT < MASTER_MIN_SALARY


def test_percentage_applies_on_a_busy_day():
    """При высокой выручке — процент, он уже больше гаранта."""
    revenue = Decimal("60000")
    costs = _compute_margin(revenue, 1)["costs"]
    assert costs["master_commission"] == revenue * MASTER_COMMISSION_PCT
    assert costs["variable"] == revenue * VARIABLE_COST_PCT


@pytest.mark.parametrize("masters", [1, 2, 3])
@pytest.mark.parametrize("profit", ["5000", "20000", "100000"])
def test_revenue_for_profit_delivers_that_profit(masters, profit):
    """Обратная проверка: заработав названную сумму, получаем нужную прибыль."""
    target = Decimal(profit)
    revenue = _revenue_for_profit(masters, target)
    got = _compute_margin(revenue, masters)["margin_rub"]
    assert abs(got - target) < Decimal("0.05")


@pytest.mark.parametrize("masters", [1, 2, 3])
def test_bigger_plan_needs_bigger_revenue(masters):
    small = _revenue_for_profit(masters, Decimal("10000"))
    big = _revenue_for_profit(masters, Decimal("50000"))
    assert big > small


def test_more_masters_never_need_less_revenue():
    """Больше людей на смене — выручки нужно не меньше, ни при каком плане."""
    for profit in ("0", "5000", "30000"):
        one, two, three = (
            _revenue_for_profit(n, Decimal(profit)) for n in (1, 2, 3)
        )
        assert one <= two <= three


def test_master_count_stops_mattering_above_the_guarantee():
    """Состав смены влияет на нужную выручку только вблизи безубыточности.

    Мастер получает процент с выручки, и в сумме это одна и та же доля
    независимо от того, на скольких человек она делится. Разница возникает
    лишь пока выручка на мастера ниже гаранта: тогда каждый лишний человек
    добавляет фиксированную сумму. Это свойство системы оплаты, а не ошибка
    расчёта, и таблица по составу смены поэтому различается только внизу.
    """
    # Скромная цель: гарант ещё действует, разница есть.
    low = [_revenue_for_profit(n, Decimal("0")) for n in (1, 2, 3)]
    assert low[0] < low[1] < low[2]

    # Амбициозная цель: все вышли на процент, разницы нет.
    high = [_revenue_for_profit(n, Decimal("30000")) for n in (1, 2, 3)]
    assert high[0] == high[1] == high[2]


def test_switch_point_follows_the_settings():
    """Точка перехода с гаранта на процент берётся из настроек.

    Раньше в коде стояло число 10 000, верное только для ставки 40% и
    гаранта 4 000. При других условиях порог считался неправильно.
    """
    # Гарант 4 000 при ставке 20% отбивается только с 20 000 на мастера.
    costs = Costs(
        fixed_daily=Decimal("9000"),
        variable_pct=Decimal("0.035"),
        master_commission_pct=Decimal("0.20"),
        master_min_salary=Decimal("4000"),
    )
    revenue = _break_even_revenue(1, costs)
    assert abs(_compute_margin(revenue, 1, costs)["margin_rub"]) < Decimal("0.05")


def test_zero_commission_falls_back_to_guarantee():
    """Мастер на голом окладе: расчёт не должен делить на ноль."""
    costs = Costs(
        fixed_daily=Decimal("9000"),
        variable_pct=Decimal("0.035"),
        master_commission_pct=Decimal("0"),
        master_min_salary=Decimal("5000"),
    )
    revenue = _break_even_revenue(2, costs)
    assert abs(_compute_margin(revenue, 2, costs)["margin_rub"]) < Decimal("0.05")


def test_costs_from_settings_change_the_threshold():
    """Поднять аренду — значит поднять порог. Иначе настройки не работают."""
    cheap = Costs(Decimal("5000"), Decimal("0.035"), Decimal("0.40"), Decimal("4000"))
    pricey = Costs(Decimal("15000"), Decimal("0.035"), Decimal("0.40"), Decimal("4000"))
    assert _break_even_revenue(2, pricey) > _break_even_revenue(2, cheap)
