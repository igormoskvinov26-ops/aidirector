"""Отбор строк в расчёте зарплаты.

Мастеру видна только его строка, и решается это на сервере. Прятать чужие
деньги на стороне браузера — значит не прятать их вообще: ответ приходит
целиком, и достаточно открыть панель разработчика.
"""

import pytest

from app.api.routes.barber_month import _only_own, _totals

MASTERS = [
    {"staff_id": 5659614, "name": "Ксения", "completed_count": 40,
     "completed_revenue": 120000, "future_count": 12, "future_revenue": 30000,
     "product_sales": 5000, "earned": 50000, "forecast": 62000},
    {"staff_id": 5659611, "name": "Арташ", "completed_count": 55,
     "completed_revenue": 180000, "future_count": 18, "future_revenue": 45000,
     "product_sales": 7000, "earned": 72700, "forecast": 90700},
    {"staff_id": 5659617, "name": "Дмитрий", "completed_count": 30,
     "completed_revenue": 90000, "future_count": 9, "future_revenue": 22000,
     "product_sales": 3000, "earned": 36300, "forecast": 45100},
]


def test_master_sees_only_himself():
    rows = _only_own(MASTERS, 5659611)
    assert len(rows) == 1
    assert rows[0]["name"] == "Арташ"


def test_unknown_staff_id_sees_nobody():
    """Чужой или неизвестный идентификатор не должен открывать всю таблицу."""
    assert _only_own(MASTERS, 999999) == []


def test_missing_binding_sees_nobody():
    """Учётная запись без привязки не получает ничего — и это безопасный отказ."""
    assert _only_own(MASTERS, None) == []


def test_totals_sum_every_master():
    totals = _totals(MASTERS)
    assert totals["completed_count"] == 125
    assert totals["completed_revenue"] == 390000
    assert totals["future_count"] == 39
    assert totals["product_sales"] == 15000
    assert totals["earned"] == 159000


def test_totals_of_one_master_equal_that_master():
    totals = _totals(_only_own(MASTERS, 5659617))
    assert totals["completed_count"] == 30
    assert totals["earned"] == 36300


def test_incomplete_salary_is_not_summed():
    """Если у кого-то зарплата не посчитана, итог по ней не показывается.

    Неполная сумма выглядит как полная: владелец увидит цифру меньше
    настоящей и примет её за факт.
    """
    broken = [dict(m) for m in MASTERS]
    broken[1]["earned"] = None
    totals = _totals(broken)
    assert totals["earned"] is None
    # Остальные показатели при этом остаются: они посчитаны честно.
    assert totals["completed_count"] == 125


def test_totals_of_nobody_are_zero_not_crash():
    totals = _totals([])
    assert totals["completed_count"] == 0
    assert totals["earned"] is None


@pytest.mark.parametrize("поле", ["rule", "forecast", "days"])
def test_служебные_поля_вычищаются(поле):
    """Условия оплаты, прогноз зарплаты и разбивка по дням — не для дашборда.

    Это расчёт ЗП, у него своя вкладка и свой вид.
    """
    from app.api.routes.barber_month import СЛУЖЕБНЫЕ_ПОЛЯ

    assert поле in СЛУЖЕБНЫЕ_ПОЛЯ


def test_начисленная_зарплата_остаётся_в_дашборде():
    """Владелец 18.09.2026 попросил показать, что остаётся салону от выручки
    мастера. Без начисленной зарплаты такой столбец не посчитать, поэтому она
    из списка вычищаемых убрана — сознательно, а не по недосмотру."""
    from app.api.routes.barber_month import СЛУЖЕБНЫЕ_ПОЛЯ

    assert "earned" not in СЛУЖЕБНЫЕ_ПОЛЯ


def test_чужая_зарплата_закрыта_отбором_а_не_вычищением():
    """Раз зарплата теперь есть в ответе, защищает её только отбор строк.

    Мастер должен получить одну строку — свою. Если этот тест упадёт,
    в дашборде откроются чужие деньги.
    """
    строки = _only_own(MASTERS, 5659611)
    assert [м["name"] for м in строки] == ["Арташ"]
    assert _only_own(MASTERS, None) == []
    assert _only_own(MASTERS, 999999) == []
