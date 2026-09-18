"""Сумма визита должна учитывать скидку, а не только цену по прайсу.

cost_to_pay — сумма к оплате, cost — по прайсу без учёта скидки; они
расходятся ровно тогда, когда на визит есть скидка. app/services/
barber_month.py на том же ответе YCLIENTS уже брал cost_to_pay первым —
здесь этого не было, и выручка визита со скидкой в базу уходила завышенной.
Обе функции теперь читают запись одинаково.
"""

from decimal import Decimal

from app.repositories.repositories import _visit_amount


def test_cost_to_pay_wins_when_there_is_a_discount():
    услуги = [{"cost": 2000, "cost_to_pay": 1500}]
    assert _visit_amount(услуги) == Decimal("1500")


def test_falls_back_to_cost_without_cost_to_pay():
    услуги = [{"cost": 2000}]
    assert _visit_amount(услуги) == Decimal("2000")


def test_falls_back_to_first_cost_when_both_missing():
    услуги = [{"first_cost": 1800}]
    assert _visit_amount(услуги) == Decimal("1800")


def test_zero_cost_to_pay_is_not_treated_as_missing():
    """0 — законное значение (бесплатная услуга), а не «поля нет»."""
    услуги = [{"cost": 2000, "cost_to_pay": 0}]
    assert _visit_amount(услуги) == Decimal("0")


def test_several_services_sum_independently():
    услуги = [
        {"cost": 2000, "cost_to_pay": 1500},
        {"cost": 1000},
    ]
    assert _visit_amount(услуги) == Decimal("2500")


def test_empty_or_missing_services_is_zero():
    assert _visit_amount([]) == Decimal("0")
    assert _visit_amount(None) == Decimal("0")
