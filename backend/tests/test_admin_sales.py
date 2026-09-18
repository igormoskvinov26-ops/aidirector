"""Продажи администраторов — отдельно от мастеров, но не вне поля зрения.

Владелец нашёл в реальном отчёте YCLIENTS продажу товара администратором
(Виктор, 1300 ₽), которой нет ни в одной строке «Записей за месяц»: там
только settings.barber_payroll_rules — трое зарегистрированных барберов.
Это не ошибка того дашборда (он про зарплату мастеров), но выручка салона
должна включать и эти деньги — отдельной сводкой, а не вклеенной в чужую
строку.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.api.routes.barber_month import future
from app.main_roles import ROLE_MASTER, ROLE_OWNER
from app.services.barber_month import calculate_admin_sales, period

НАЙДЕН_БАРБЕР = 5659614  # совпадает с одним из settings.barber_payroll_rules в тестовом .env
ВИКТОР = 777001
ЕКАТЕРИНА = 777002
СРЕДА = datetime(2026, 9, 18, 12, 0, tzinfo=period.__globals__["MOSCOW"])

СОТРУДНИКИ = [
    {"id": ВИКТОР, "name": "Виктор / Старший администратор"},
    {"id": ЕКАТЕРИНА, "name": "Екатерина / Администратор"},
]


def _visit(id_, staff_id, dt, attendance=1, cost=0, deleted=False):
    return {
        "id": id_, "staff_id": staff_id, "datetime": dt.isoformat(),
        "visit_attendance": attendance, "deleted": deleted,
        "services": [{"cost_to_pay": cost}] if cost else [],
    }


# --------------------------------------------------------------------------- #
# calculate_admin_sales — чистая функция, без сети
# --------------------------------------------------------------------------- #


def test_продажа_администратора_попадает_в_сводку():
    products = [{"staff_id": ВИКТОР, "date": СРЕДА.date().isoformat(), "amount": 1300}]
    сводка = calculate_admin_sales([], products, СРЕДА, СОТРУДНИКИ)
    assert сводка["masters"] == [{
        "staff_id": ВИКТОР, "name": "Виктор / Старший администратор",
        "completed_count": 0, "completed_revenue": 0.0, "product_sales": 1300.0,
    }]
    assert сводка["totals"] == {
        "completed_count": 0, "completed_revenue": 0.0, "product_sales": 1300.0,
    }


def test_услуга_барбера_не_попадает_к_администраторам():
    """Барбер не входит в admin_staff — его записи должны быть проигнорированы,
    даже если по ошибке окажутся в тех же records."""
    records = [_visit(1, НАЙДЕН_БАРБЕР, СРЕДА - timedelta(hours=1), cost=5000)]
    сводка = calculate_admin_sales(records, [], СРЕДА, СОТРУДНИКИ)
    assert сводка["masters"] == []
    assert сводка["totals"]["completed_revenue"] == 0.0


def test_выполненная_услуга_администратора_считается():
    records = [_visit(2, ЕКАТЕРИНА, СРЕДА - timedelta(hours=1), cost=2000)]
    сводка = calculate_admin_sales(records, [], СРЕДА, СОТРУДНИКИ)
    assert сводка["totals"]["completed_count"] == 1
    assert сводка["totals"]["completed_revenue"] == 2000.0


def test_будущая_запись_администратора_не_считается():
    """Эта сводка — только про то, что уже произошло, без прогноза."""
    records = [_visit(3, ЕКАТЕРИНА, СРЕДА + timedelta(days=2), attendance=0)]
    сводка = calculate_admin_sales(records, [], СРЕДА, СОТРУДНИКИ)
    assert сводка["masters"] == []


def test_нет_данных_о_косметике_даёт_none_а_не_ноль():
    """products is None — продажи неизвестны, а не равны нулю: 'неполная сумма
    выглядит как полная', та же дисциплина, что у _expected() для мастеров."""
    сводка = calculate_admin_sales([], None, СРЕДА, СОТРУДНИКИ)
    assert сводка["totals"]["product_sales"] is None


def test_нет_активных_администраторов_даёт_пустую_сводку():
    сводка = calculate_admin_sales([], [], СРЕДА, [])
    assert сводка == {"masters": [], "totals": {
        "completed_count": 0, "completed_revenue": 0.0, "product_sales": 0.0,
    }}


# --------------------------------------------------------------------------- #
# Маршрут /future — видимость по роли и company_revenue
# --------------------------------------------------------------------------- #


def _fake_request(role, staff_id=None):
    return SimpleNamespace(state=SimpleNamespace(role=role, staff_id=staff_id))


def _fake_report():
    """Форма ответа report(): один барбер плюс продажа администратора."""
    return {
        "month_start": "2026-09-01", "month_end": "2026-09-30",
        "as_of": СРЕДА.isoformat(), "updated_at": СРЕДА.isoformat(),
        "warnings": [],
        "masters": [{
            "staff_id": НАЙДЕН_БАРБЕР, "name": "Ксения", "rule": {}, "days": [],
            "completed_count": 10, "completed_revenue": 100000,
            "future_count": 0, "future_revenue": 0,
            "product_sales": 5000, "earned": 42000, "forecast": 42000,
        }],
        "admin_sales": {
            "masters": [{
                "staff_id": ВИКТОР, "name": "Виктор",
                "completed_count": 0, "completed_revenue": 0.0, "product_sales": 1300.0,
            }],
            "totals": {"completed_count": 0, "completed_revenue": 0.0, "product_sales": 1300.0},
        },
    }


async def _fake_safe_report():
    return _fake_report()


@pytest.mark.asyncio
async def test_владелец_видит_продажи_администраторов_и_итог_с_ними(monkeypatch):
    monkeypatch.setattr(
        "app.api.routes.barber_month._safe_report",
        _fake_safe_report,
    )
    result = await future(_fake_request(ROLE_OWNER))
    assert result["admin_sales"]["totals"]["product_sales"] == 1300.0

    # 100000 (услуги Ксении) + 5000 (её косметика) + 0 (услуги администраторов)
    # + 1300 (их продажи) = 106300 — вся выручка салона, не только барберов.
    assert result["totals"]["company_revenue"] == pytest.approx(106300.0)
    # А строка «Итого по мастерам» — по-прежнему только барберы, без подмены:
    # её сумма обязана совпадать с видимой таблицей выше.
    assert result["totals"]["expected_revenue"] == pytest.approx(105000.0)


@pytest.mark.asyncio
async def test_мастер_не_видит_чужие_продажи_и_company_revenue(monkeypatch):
    monkeypatch.setattr(
        "app.api.routes.barber_month._safe_report",
        _fake_safe_report,
    )
    result = await future(_fake_request(ROLE_MASTER, staff_id=НАЙДЕН_БАРБЕР))
    assert "admin_sales" not in result
    assert result["totals"]["company_revenue"] is None


@pytest.mark.asyncio
async def test_отсутствие_продаж_администраторов_не_ломает_company_revenue(monkeypatch):
    """Сотрудников кроме барберов не было вовсе — не ошибка, просто ноль."""
    report = _fake_report()
    report["admin_sales"] = {
        "masters": [], "totals": {"completed_count": 0, "completed_revenue": 0.0,
                                    "product_sales": 0.0},
    }
    async def _fake_safe_report_override():
        return report

    monkeypatch.setattr(
        "app.api.routes.barber_month._safe_report", _fake_safe_report_override
    )
    result = await future(_fake_request(ROLE_OWNER))
    assert result["admin_sales"]["masters"] == []
    assert result["totals"]["company_revenue"] == pytest.approx(105000.0)
