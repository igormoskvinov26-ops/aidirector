"""Предупреждение о рассинхронизации id сотрудника (решение владельца
22.11.2026): владелец сообщил, что у одного из барберов (Дарья) «Расчёт
зарплаты» показывает пустые цифры. Наиболее вероятная причина — сохранённая
в настройках привязка к id сотрудника YCLIENTS больше не соответствует
никому из активных сотрудников (профиль пересоздан, уволен/скрыт и т.п.):
её визиты есть, но ни один не находит совпадения по id, и строка тихо
обнуляется. Явное предупреждение делает эту рассинхронизацию видимой вместо
того, чтобы владелец гадал, почему цифры пустые.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.config import settings
from app.services import barber_month as bm

MOSCOW = ZoneInfo("Europe/Moscow")
СЕЙЧАС = datetime(2026, 11, 15, 12, 0, tzinfo=MOSCOW)


async def _fake_source(*, schedule=None, products=None, staff=None, warnings=None):
    async def source(now):
        return [], schedule, products, staff, list(warnings or []), СЕЙЧАС.isoformat()
    return source


@pytest.mark.asyncio
async def test_предупреждение_когда_id_барбера_не_среди_активных(monkeypatch):
    settings.barber_payroll_rules = [
        {"staff_id": 999, "name": "Дарья", "guarantee": 0, "service_rate": 0.4, "product_rate": 0.1},
    ]
    monkeypatch.setattr(bm, "source", await _fake_source(
        schedule=[], products=[], staff=[{"id": 111, "name": "Другой сотрудник"}],
    ))

    итог = await bm.report()

    assert any(w.startswith("«Дарья»") and "999" in w for w in итог["warnings"])


@pytest.mark.asyncio
async def test_без_предупреждения_когда_id_совпадает(monkeypatch):
    settings.barber_payroll_rules = [
        {"staff_id": 111, "name": "Дарья", "guarantee": 0, "service_rate": 0.4, "product_rate": 0.1},
    ]
    monkeypatch.setattr(bm, "source", await _fake_source(
        schedule=[], products=[], staff=[{"id": 111, "name": "Дарья"}],
    ))

    итог = await bm.report()

    assert not any(w.startswith("«") for w in итог["warnings"])


@pytest.mark.asyncio
async def test_список_сотрудников_недоступен_сверка_пропускается(monkeypatch):
    """Staff is None — YCLIENTS не ответил на список сотрудников (уже есть
    своё предупреждение). Сверку в этом случае делать нельзя: пустой список
    означал бы, что ВСЕ барберы рассинхронизированы, хотя дело в сети."""
    settings.barber_payroll_rules = [
        {"staff_id": 999, "name": "Дарья", "guarantee": 0, "service_rate": 0.4, "product_rate": 0.1},
    ]
    monkeypatch.setattr(bm, "source", await _fake_source(
        schedule=[], products=[], staff=None,
        warnings=["Список сотрудников недоступен: продажи администраторов не показаны."],
    ))

    итог = await bm.report()

    assert not any(w.startswith("«") for w in итог["warnings"])
