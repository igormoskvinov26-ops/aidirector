"""Арифметика безубыточности.

Проверяется не совпадение с заранее выписанными числами, а свойство: при
выручке, равной порогу, день выходит ровно в ноль. Такой тест переживёт
изменение аренды или процента мастеру — а именно эти числа и будут меняться.
"""

from decimal import Decimal

import pytest

from app.services.finance import (
    DEFAULT_COSTS,
    FIXED_DAILY_COST,
    MASTER_COMMISSION_PCT,
    VARIABLE_COST_PCT,
    Costs,
    _break_even_revenue,
    _compute_margin,
    _revenue_for_profit,
)

# Расходы для проверок, где важна не величина, а поведение формулы.
SIMPLE = Costs(
    fixed_daily=Decimal("9000"),
    variable_pct=Decimal("0.035"),
    master_commission_pct=Decimal("0.40"),
    product_commission_pct=Decimal("0.10"),
    guarantees=(Decimal("4000"),),
)


@pytest.mark.parametrize("masters", [1, 2, 3])
def test_break_even_revenue_zeroes_the_day(masters):
    """На пороге день не в минусе и не в плюсе."""
    revenue = _break_even_revenue(masters)
    margin = _compute_margin(revenue, Decimal("0"), masters)
    assert abs(margin["margin_rub"]) < Decimal("0.05")


@pytest.mark.parametrize("masters", [1, 2, 3])
def test_rouble_below_break_even_is_a_loss(masters):
    revenue = _break_even_revenue(masters) - Decimal("100")
    assert _compute_margin(revenue, Decimal("0"), masters)["margin_rub"] < 0


@pytest.mark.parametrize("masters", [1, 2, 3])
def test_rouble_above_break_even_is_a_profit(masters):
    revenue = _break_even_revenue(masters) + Decimal("100")
    assert _compute_margin(revenue, Decimal("0"), masters)["margin_rub"] > 0


def test_more_masters_never_lower_the_bar():
    """Каждый следующий человек на смене планку не опускает.

    Строгого роста здесь не требуется: он зависит от того, действует ли ещё
    гарант, а это меняется вместе с расходами. Свойство, которое верно
    всегда, — планка не падает.
    """
    one, two, three = (_break_even_revenue(n) for n in (1, 2, 3))
    assert one <= two <= three


def test_zero_masters_treated_as_one():
    """День без единого мастера всё равно стоит денег: аренда не отменяется."""
    assert _break_even_revenue(0) == _break_even_revenue(1)
    assert _break_even_revenue(0) > FIXED_DAILY_COST


def test_guarantee_applies_on_a_quiet_day():
    """При низкой выручке мастер получает гарант, а не процент."""
    revenue = Decimal("5000")
    guarantee = SIMPLE.guarantees[0]
    costs = _compute_margin(revenue, Decimal("0"), 1, SIMPLE)["costs"]
    assert costs["master_commission"] == guarantee
    assert revenue * SIMPLE.master_commission_pct < guarantee


def test_percentage_applies_on_a_busy_day():
    """При высокой выручке — процент, он уже больше гаранта."""
    revenue = Decimal("60000")
    costs = _compute_margin(revenue, Decimal("0"), 1, SIMPLE)["costs"]
    assert costs["master_commission"] == revenue * SIMPLE.master_commission_pct
    assert costs["variable"] == revenue * SIMPLE.variable_pct


def test_cosmetics_are_paid_at_their_own_rate():
    """С косметики мастеру идёт свой процент, не такой, как с услуг."""
    services, products = Decimal("60000"), Decimal("10000")
    costs = _compute_margin(services, products, 1, SIMPLE)["costs"]
    expected = (
        services * SIMPLE.master_commission_pct
        + products * SIMPLE.product_commission_pct
    )
    assert costs["master_commission"] == expected


def test_bigger_guarantee_raises_the_threshold():
    """Мастер с более крупным гарантом поднимает планку дня."""
    cheap = Costs(Decimal("9000"), Decimal("0.035"), Decimal("0.40"),
                  Decimal("0.10"), (Decimal("4000"),))
    pricey = Costs(Decimal("9000"), Decimal("0.035"), Decimal("0.40"),
                   Decimal("0.10"), (Decimal("8000"),))
    assert _break_even_revenue(1, pricey) > _break_even_revenue(1, cheap)


def test_shift_takes_the_largest_guarantees():
    """Кто выйдет — заранее неизвестно, поэтому берётся худший случай."""
    costs = Costs(Decimal("9000"), Decimal("0.035"), Decimal("0.40"), Decimal("0.10"),
                  (Decimal("4000"), Decimal("5000"), Decimal("4000")))
    assert costs.shift_guarantees(1) == (Decimal("5000"),)
    assert costs.shift_guarantees(2) == (Decimal("5000"), Decimal("4000"))
    assert sum(costs.shift_guarantees(3)) == Decimal("13000")


def test_more_masters_than_known_guarantees():
    """Если вышло больше людей, чем описано, расчёт не должен падать."""
    costs = Costs(Decimal("9000"), Decimal("0.035"), Decimal("0.40"), Decimal("0.10"),
                  (Decimal("4000"),))
    assert len(costs.shift_guarantees(3)) == 3


@pytest.mark.parametrize("masters", [1, 2, 3])
@pytest.mark.parametrize("profit", ["5000", "20000", "100000"])
def test_revenue_for_profit_delivers_that_profit(masters, profit):
    """Обратная проверка: заработав названную сумму, получаем нужную прибыль."""
    target = Decimal(profit)
    revenue = _revenue_for_profit(masters, target)
    got = _compute_margin(revenue, Decimal("0"), masters)["margin_rub"]
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


def test_master_count_matters_only_while_the_guarantee_binds():
    """Состав смены влияет на нужную выручку только внизу шкалы.

    Мастер получает процент с выручки, и в сумме это одна и та же доля
    независимо от того, на скольких человек она делится. Разница возникает,
    лишь пока выручка на мастера ниже гаранта: тогда каждый лишний человек
    добавляет фиксированную сумму. Это свойство системы оплаты, а не ошибка
    расчёта, и таблица по составу смены поэтому различается только внизу.

    Расходы заданы явно, а не взяты по умолчанию: где именно проходит
    граница, зависит от их величины, и тест не должен ломаться каждый раз,
    когда владелец меняет аренду.
    """
    cheap = Costs(
        fixed_daily=Decimal("5000"),
        variable_pct=Decimal("0.035"),
        master_commission_pct=Decimal("0.40"),
        product_commission_pct=Decimal("0.10"),
        guarantees=(Decimal("4000"), Decimal("4000"), Decimal("4000")),
    )
    # Низкий порог: выручка на мастера мала, гарант ещё действует.
    low = [_revenue_for_profit(n, Decimal("0"), cheap) for n in (1, 2, 3)]
    assert low[0] < low[1] < low[2]

    # Амбициозная цель: все вышли на процент, разницы нет.
    high = [_revenue_for_profit(n, Decimal("30000"), cheap) for n in (1, 2, 3)]
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
        product_commission_pct=Decimal("0.10"),
        guarantees=(Decimal("4000"),),
    )
    revenue = _break_even_revenue(1, costs)
    assert abs(_compute_margin(revenue, Decimal("0"), 1, costs)["margin_rub"]) < Decimal("0.05")


def test_zero_commission_falls_back_to_guarantee():
    """Мастер на голом окладе: расчёт не должен делить на ноль."""
    costs = Costs(
        fixed_daily=Decimal("9000"),
        variable_pct=Decimal("0.035"),
        master_commission_pct=Decimal("0"),
        product_commission_pct=Decimal("0"),
        guarantees=(Decimal("5000"), Decimal("5000")),
    )
    revenue = _break_even_revenue(2, costs)
    assert abs(_compute_margin(revenue, Decimal("0"), 2, costs)["margin_rub"]) < Decimal("0.05")


def test_costs_from_settings_change_the_threshold():
    """Поднять аренду — значит поднять порог. Иначе настройки не работают."""
    cheap = Costs(Decimal("5000"), Decimal("0.035"), Decimal("0.40"),
                  Decimal("0.10"), (Decimal("4000"),))
    pricey = Costs(Decimal("15000"), Decimal("0.035"), Decimal("0.40"),
                   Decimal("0.10"), (Decimal("4000"),))
    assert _break_even_revenue(2, pricey) > _break_even_revenue(2, cheap)
