"""Страница Владельца: доход, расходы, прибыль и темп против прошедшего месяца."""

from datetime import date
from decimal import Decimal

import pytest

from app.services import acquiring
from app.services.owner_overview import (
    итоги_месяца, контрольные_точки, прогноз_месяца, свести, _месяцы,
)


def _t(amount, kind=None, title=None, day="2026-10-02"):
    return {"amount": amount, "sold_item_type": kind, "date": day,
            "expense": {"title": title} if title else None}


def test_итоги_месяца_делят_продажи_расходы_и_переводы():
    итог = итоги_месяца([
        _t(3000, "service"), _t(500, "goods_transaction"),
        _t(-1000, title="Аренда"), _t(-200, title="Реклама"),
        _t(-5000, title="Инкассация"),  # перевод между счетами — не трата
        {**_t(-999, title="Аренда"), "deleted": True},
    ])
    assert итог["income"] == 3500 and итог["expenses"] == 1200
    assert итог["groups"] == {"Аренда и постоянные": 1000, "Маркетинг": 200}


def test_без_статьи_не_считается_расходом():
    """Сверка с отчётом YCLIENTS 05.10.2026: инкассация у владельца заведена
    без статьи — YCLIENTS в своём отчёте «Расходы» её не считает, значит и
    здесь не должна."""
    итог = итоги_месяца([
        _t(3000, "service"),
        _t(-1000, title="Аренда"),
        _t(-700),  # без статьи — то же, что перевод
    ])
    assert итог["expenses"] == 1000
    assert итог["groups"] == {"Аренда и постоянные": 1000}


def test_темп_и_цвета_как_просил_владелец():
    месяцы = _месяцы(date(2026, 9, 15))
    по = {m: {"income": Decimal(400000), "expenses": Decimal(300000), "groups": {}} for m in месяцы}
    # текущий сентябрь: 15 из 30 дней = 50%. Бюджет расходов 300к, план прибыли 100к → план дохода 400к.
    по["2026-09"] = {"income": Decimal(240000), "expenses": Decimal(160000), "groups": {"ФОТ": Decimal(160000)}}
    r = свести(по, Decimal(100000), date(2026, 9, 15))
    assert r["elapsed_pct"] == 50.0
    assert r["income"]["plan"] == 400000 and r["income"]["pct_of_plan"] == 60.0 and r["income"]["ok"] is True
    assert r["expenses"]["budget"] == 300000 and r["expenses"]["ok"] is False  # 53% бюджета при 50% месяца
    assert r["profit"]["value"] == 80000 and r["profit"]["pace"] == 50000 and r["profit"]["ok"] is True
    assert len(r["history"]) == 6 and r["history"][-1]["partial"]


def test_без_плана_прибыли_плана_дохода_нет():
    месяцы = _месяцы(date(2026, 10, 4))
    по = {m: {"income": Decimal(0), "expenses": Decimal(0), "groups": {}} for m in месяцы}
    r = свести(по, Decimal(0), date(2026, 10, 4))
    assert r["income"]["plan"] is None and r["income"]["ok"] is None
    assert r["expenses"]["budget"] is None


@pytest.mark.asyncio
async def test_отчёт_за_день_без_этого_дня_не_записывается(monkeypatch):
    monkeypatch.setattr(acquiring, "разобрать", lambda c, n: {
        "rows": [{"date": date(2026, 10, 1), "amount": Decimal(10), "fee": Decimal(0), "net": Decimal(10)}],
        "skipped": 0, "header_total": None, "matches_header": None, "columns": {}})
    with pytest.raises(ValueError, match="нет операций за 03.10.2026"):
        await acquiring.сохранить(None, b"x", "r.csv", date(2026, 10, 3))


def test_прогноз_месяца_фот_доля_и_прочие_среднее():
    """Решение владельца 19.11.2026: ФОТ — средний % от дохода за прошлые
    месяцы, прочие расходы — их средняя абсолютная сумма, не зависящая
    от выручки. Прошлые месяцы: доход 1 000 000, ФОТ 300 000 (30%),
    прочие 250 000 (аренда+коммуналка+закупки+маркетинг)."""
    прошлый = {"income": Decimal(1_000_000), "expenses": Decimal(550_000),
               "groups": {"ФОТ": Decimal(300_000)}}
    по_месяцам = {
        "2026-07": прошлый, "2026-08": прошлый, "2026-09": прошлый,
        "2026-10": {"income": Decimal(400_000), "expenses": Decimal(0), "groups": {}},
    }
    r = прогноз_месяца(по_месяцам, date(2026, 10, 15), Decimal(200_000))
    assert r["revenue"] == 600_000.0
    assert r["payroll_pct_of_revenue"] == 30.0
    assert r["payroll"] == 180_000.0
    assert r["other_expenses"] == 250_000.0
    assert r["profit"] == 170_000.0
    assert r["months_used"] == 3


def test_прогноз_месяца_без_истории_ничего_не_считает():
    по_месяцам = {"2026-10": {"income": Decimal(400_000), "expenses": Decimal(0), "groups": {}}}
    r = прогноз_месяца(по_месяцам, date(2026, 10, 15), Decimal(200_000))
    assert r["payroll"] is None and r["other_expenses"] is None and r["profit"] is None
    assert r["revenue"] == 600_000.0  # выручка не зависит от истории
    assert r["months_used"] == 0


def _продажа(day: str, amount: float) -> dict:
    return {"amount": amount, "sold_item_type": "service", "date": day}


def test_контрольные_точки_прошлая_дата_берёт_факт_по_кассе():
    транзакции = [_продажа("2026-10-05", 1000), _продажа("2026-10-10", 2000),
                  _продажа("2026-10-20", 3000)]
    точки = контрольные_точки(транзакции, None, date(2026, 10, 28))
    по_дате = {т["date"]: т for т in точки}
    assert по_дате["2026-10-10"]["revenue"] == 3000.0 and по_дате["2026-10-10"]["passed"] is True
    assert по_дате["2026-10-25"]["revenue"] == 6000.0 and по_дате["2026-10-25"]["passed"] is True
    assert по_дате["2026-10-10"]["label"] == "Выплата ЗП"
    assert по_дате["2026-10-25"]["label"] == "Аванс, аренда и коммуналка"


def test_контрольные_точки_будущая_дата_добавляет_запись_вперёд():
    транзакции = [_продажа("2026-10-02", 1000), _продажа("2026-10-05", 500)]
    вперёд_по_дням = {date(2026, 10, 8): Decimal(700), date(2026, 10, 10): Decimal(300),
                      date(2026, 10, 20): Decimal(10_000)}
    точки = контрольные_точки(транзакции, вперёд_по_дням, date(2026, 10, 5))
    по_дате = {т["date"]: т for т in точки}
    assert по_дате["2026-10-10"]["revenue"] == 2500.0 and по_дате["2026-10-10"]["passed"] is False
    assert по_дате["2026-10-25"]["revenue"] == 12_500.0 and по_дате["2026-10-25"]["passed"] is False


def test_контрольные_точки_без_записи_вперёд_не_угадывает():
    точки = контрольные_точки([], None, date(2026, 10, 5))
    assert all(т["revenue"] is None for т in точки)
