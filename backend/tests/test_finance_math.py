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
    _break_even_revenue,
    _compute_margin,
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
