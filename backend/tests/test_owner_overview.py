"""Страница Владельца: доход, расходы, прибыль и темп против прошедшего месяца."""

from datetime import date
from decimal import Decimal

import pytest

from app.services import acquiring
from app.services.owner_overview import итоги_месяца, свести, _месяцы


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
