"""Возвращаемость за текущий месяц — первый из двух показателей на «Записях
за месяц» (решение владельца 18.09.2026, уточнено в том же разговоре).

Отличается от finance.get_return_rate (второй показатель, за всё время в
базе) тем, что смотрит только на записи текущего месяца — те же, что и
основная таблица страницы: выполненные с начала месяца плюс подтверждённые
будущие до конца месяца. Клиент — «вернувшийся» целиком, если таких записей
к этому мастеру за месяц у него две или больше. Знаменатель — его клиенты
за месяц, то есть процент свой у каждого мастера.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.api.routes.barber_month import future
from app.main_roles import ROLE_MASTER, ROLE_OWNER
from app.services.barber_month import calculate_month_return_rate, period

КСЕНИЯ = 5659614  # settings.barber_payroll_rules по умолчанию (тестовый .env)
АРТАШ = 5659611
СРЕДА = datetime(2026, 9, 18, 12, 0, tzinfo=period.__globals__["MOSCOW"])

ПРАВИЛА = [{"staff_id": КСЕНИЯ, "name": "Ксения"}, {"staff_id": АРТАШ, "name": "Арташ"}]


def _record(id_, staff_id, client_id, dt, attendance=1, deleted=False):
    return {
        "id": id_, "staff_id": staff_id, "client": {"id": client_id},
        "datetime": dt.isoformat(), "visit_attendance": attendance, "deleted": deleted,
    }


def _row(итог, staff_id):
    return next(m for m in итог["masters"] if m["staff_id"] == staff_id)


def test_второй_визит_в_этом_месяце_это_возврат():
    records = [
        _record(1, КСЕНИЯ, 100, СРЕДА - timedelta(days=10)),
        _record(2, КСЕНИЯ, 100, СРЕДА - timedelta(days=1)),
    ]
    итог = calculate_month_return_rate(records, СРЕДА, ПРАВИЛА)
    ксения = _row(итог, КСЕНИЯ)
    assert ксения["clients_total"] == 1
    assert ксения["clients_returned"] == 1
    assert ксения["return_rate_pct"] == 100.0


def test_визиты_к_разным_мастерам_не_считаются_возвратом():
    records = [
        _record(1, КСЕНИЯ, 100, СРЕДА - timedelta(days=10)),
        _record(2, АРТАШ, 100, СРЕДА - timedelta(days=1)),
    ]
    итог = calculate_month_return_rate(records, СРЕДА, ПРАВИЛА)
    assert _row(итог, КСЕНИЯ)["clients_returned"] == 0
    assert _row(итог, АРТАШ)["clients_returned"] == 0


def test_отменённые_и_неявки_не_считаются():
    records = [
        _record(1, КСЕНИЯ, 100, СРЕДА - timedelta(days=10), attendance=1),
        _record(2, КСЕНИЯ, 100, СРЕДА - timedelta(days=5), attendance=-1),  # неявка
        _record(3, КСЕНИЯ, 100, СРЕДА - timedelta(days=4), attendance=1, deleted=True),
    ]
    итог = calculate_month_return_rate(records, СРЕДА, ПРАВИЛА)
    ксения = _row(итог, КСЕНИЯ)
    assert ксения["clients_total"] == 1
    assert ксения["clients_returned"] == 0


def test_подтверждённая_будущая_запись_идёт_в_знаменатель():
    """Владелец: «выполненных записей или записанных до конца месяца» —
    будущая подтверждённая запись тоже делает клиента частью пула месяца."""
    records = [
        _record(1, КСЕНИЯ, 100, СРЕДА - timedelta(days=10), attendance=1),
        _record(2, КСЕНИЯ, 100, СРЕДА + timedelta(days=3), attendance=0),  # запись впереди
    ]
    итог = calculate_month_return_rate(records, СРЕДА, ПРАВИЛА)
    ксения = _row(итог, КСЕНИЯ)
    assert ксения["clients_total"] == 1
    assert ксения["clients_returned"] == 1


def test_запись_вне_текущего_месяца_не_считается():
    records = [_record(1, КСЕНИЯ, 100, СРЕДА - timedelta(days=60))]
    итог = calculate_month_return_rate(records, СРЕДА, ПРАВИЛА)
    assert _row(итог, КСЕНИЯ)["clients_total"] == 0


def test_без_клиентов_процент_не_ноль_а_неизвестен():
    итог = calculate_month_return_rate([], СРЕДА, ПРАВИЛА)
    ксения = _row(итог, КСЕНИЯ)
    assert ксения["clients_total"] == 0
    assert ксения["return_rate_pct"] is None


def test_сортировка_по_возвращаемости_лучшие_первыми():
    records = [
        _record(1, КСЕНИЯ, 100, СРЕДА - timedelta(days=10)),
        _record(2, КСЕНИЯ, 100, СРЕДА - timedelta(days=1)),
        _record(3, АРТАШ, 200, СРЕДА - timedelta(days=10)),
        _record(4, АРТАШ, 201, СРЕДА - timedelta(days=1)),
    ]
    итог = calculate_month_return_rate(records, СРЕДА, ПРАВИЛА)
    порядок = [m["staff_id"] for m in итог["masters"]]
    assert порядок.index(КСЕНИЯ) < порядок.index(АРТАШ)


def test_все_настроенные_барберы_присутствуют_даже_без_записей():
    итог = calculate_month_return_rate([], СРЕДА, ПРАВИЛА)
    имена = {m["staff_id"] for m in итог["masters"]}
    assert имена == {КСЕНИЯ, АРТАШ}


# --------------------------------------------------------------------------- #
# Маршрут /future — видимость по роли, как и у admin_sales
# --------------------------------------------------------------------------- #


def _fake_request(role, staff_id=None):
    return SimpleNamespace(state=SimpleNamespace(role=role, staff_id=staff_id))


def _fake_report():
    return {
        "month_start": "2026-09-01", "month_end": "2026-09-30",
        "as_of": СРЕДА.isoformat(), "updated_at": СРЕДА.isoformat(),
        "warnings": [],
        "masters": [{
            "staff_id": КСЕНИЯ, "name": "Ксения", "rule": {}, "days": [],
            "completed_count": 10, "completed_revenue": 100000,
            "future_count": 0, "future_revenue": 0,
            "product_sales": 5000, "earned": 42000, "forecast": 42000,
        }],
        "admin_sales": {"masters": [], "totals": {
            "completed_count": 0, "completed_revenue": 0.0, "product_sales": 0.0,
        }},
        "return_rate_month": {"masters": [
            {"staff_id": КСЕНИЯ, "name": "Ксения",
             "clients_total": 5, "clients_returned": 2, "return_rate_pct": 40.0},
        ]},
    }


async def _fake_safe_report():
    return _fake_report()


@pytest.mark.asyncio
async def test_владелец_видит_месячную_возвращаемость(monkeypatch):
    monkeypatch.setattr("app.api.routes.barber_month._safe_report", _fake_safe_report)
    result = await future(_fake_request(ROLE_OWNER))
    assert result["return_rate_month"]["masters"][0]["return_rate_pct"] == 40.0


@pytest.mark.asyncio
async def test_мастер_не_видит_месячную_возвращаемость(monkeypatch):
    monkeypatch.setattr("app.api.routes.barber_month._safe_report", _fake_safe_report)
    result = await future(_fake_request(ROLE_MASTER, staff_id=КСЕНИЯ))
    assert "return_rate_month" not in result
