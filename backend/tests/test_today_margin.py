"""Сегодняшний день считается по выработке каждого мастера.

Порога «в сутки» как одного числа не существует: он зависит от того, как
выручка легла между мастерами. Мастер, не добравший до гаранта, обходится
салону дороже, чем тот же рубль, заработанный его напарником сверх гаранта.
Поэтому за прошедшее считаем по фактам, а не по среднему.
"""

from decimal import Decimal

import pytest

from app.services.finance import (
    Costs,
    _break_even_for_split,
    ceil_thousand,
    payout_by_master,
    revenue_zone,
)

COSTS = Costs(
    fixed_daily=Decimal("15000"),
    variable_pct=Decimal("0"),
    master_commission_pct=Decimal("0.40"),
    product_commission_pct=Decimal("0.10"),
    guarantees=(Decimal("4000"), Decimal("4000"), Decimal("4000")),
)


def test_even_split_threshold():
    """Двое поровну: платят 40% со всей выручки, гарант не включается."""
    assert _break_even_for_split([Decimal("1"), Decimal("1")], COSTS) == Decimal("25000")


def test_one_master_threshold_matches_the_owners_example():
    """Разбор владельца: при постоянных 15 000 один мастер выходит в ноль на 25 000."""
    assert _break_even_for_split([Decimal("1")], COSTS) == Decimal("25000")


def test_idle_partner_raises_the_threshold():
    """Напарник без выручки всё равно получает гарант — планка растёт."""
    alone = _break_even_for_split([Decimal("1")], COSTS)
    with_idle = _break_even_for_split([Decimal("1"), Decimal("0")], COSTS)
    assert with_idle > alone
    # Гарант 4 000 при доле салона 60 копеек с рубля стоит 4 000 / 0,6.
    # Простой напарника обходится дороже самого гаранта: чтобы покрыть
    # доплату, надо заработать больше — часть заработанного снова уйдёт
    # мастеру процентом.
    expected = Decimal("4000") / Decimal("0.6")
    assert abs((with_idle - alone) - expected) < Decimal("1")


def test_skew_sits_between_even_and_idle():
    even = _break_even_for_split([Decimal("1"), Decimal("1")], COSTS)
    skewed = _break_even_for_split([Decimal("8"), Decimal("2")], COSTS)
    idle = _break_even_for_split([Decimal("1"), Decimal("0")], COSTS)
    assert even <= skewed <= idle


def test_threshold_is_a_real_zero():
    """Проверка обратным ходом: на пороге день выходит ровно в ноль."""
    shares = [Decimal("7"), Decimal("3")]
    revenue = _break_even_for_split(shares, COSTS)
    total = sum(shares, Decimal("0"))
    per_master = [(revenue * s / total, Decimal("0")) for s in shares]
    result = revenue - COSTS.fixed_daily - payout_by_master(per_master, COSTS)
    assert abs(result) < Decimal("0.05")


def test_cosmetics_lower_the_threshold():
    """Проданная косметика приносит больше, чем стоит, и опускает планку."""
    dry = _break_even_for_split([Decimal("1")], COSTS)
    with_products = _break_even_for_split([Decimal("1")], COSTS, Decimal("5000"))
    assert with_products < dry


def test_empty_day_does_not_divide_by_zero():
    """День без выручки — не повод падать: планка считается как при равной загрузке."""
    assert _break_even_for_split([Decimal("0"), Decimal("0")], COSTS) > 0


# ── Округление порогов и три зоны ───────────────────────────────────────────


@pytest.mark.parametrize(
    "value,expected",
    [
        ("20843", "21000"),
        ("27923", "28000"),
        ("21000", "21000"),  # ровная тысяча остаётся собой
        ("20001", "21000"),
        ("0", "0"),
    ],
)
def test_ceil_thousand(value, expected):
    """Только вверх: округление вниз опустило бы планку ниже настоящей."""
    assert ceil_thousand(Decimal(value)) == Decimal(expected)


@pytest.mark.parametrize(
    "revenue,zone",
    [
        ("0", "red"),
        ("20999", "red"),
        ("21000", "amber"),
        ("24000", "amber"),
        ("27999", "amber"),
        ("28000", "green"),
        ("50000", "green"),
    ],
)
def test_revenue_zone(revenue, zone):
    """Границы включаются в верхнюю зону: ровно 21 000 — уже не красный."""
    assert revenue_zone(Decimal(revenue), Decimal("21000"), Decimal("28000")) == zone


def test_shown_boundary_is_never_softer_than_the_real_one():
    """Показанная граница не должна быть мягче настоящей.

    Округление вверх означает, что при выручке между настоящим порогом и
    круглым числом день ещё считается красным. Это осторожно и правильно:
    лучше лишний раз не обрадовать. Расходы здесь нарочно такие, чтобы порог
    не попал на ровную тысячу, — иначе проверять нечего.
    """
    uneven = Costs(
        fixed_daily=Decimal("11776.32"),
        variable_pct=Decimal("0.035"),
        master_commission_pct=Decimal("0.40"),
        product_commission_pct=Decimal("0.10"),
        guarantees=(Decimal("4000"), Decimal("4000")),
    )
    exact = _break_even_for_split([Decimal("1"), Decimal("1")], uneven)
    shown = ceil_thousand(exact)
    assert shown > exact, "порог должен быть не круглым, иначе тест бессмыслен"

    # Выручка выше настоящего порога, но ниже показанного — всё ещё красная.
    between = (exact + shown) / 2
    assert revenue_zone(between, shown, shown * 2) == "red"
    # А ровно на показанной границе — уже нет.
    assert revenue_zone(shown, shown, shown * 2) == "amber"
