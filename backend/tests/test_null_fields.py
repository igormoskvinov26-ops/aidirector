"""Поля ответа YCLIENTS, пришедшие как null, не должны ронять выгрузку.

28.09.2026 в 16:41 выгрузка визитов встала на одной записи с "client": null —
так YCLIENTS присылает перерыв мастера и гостя без записи. Код читал поле как
item.get("client", {}).get("id"): значение по умолчанию подставляется только
для отсутствующего ключа, а null превращался в None.get(...) и
AttributeError. Двое суток данные не обновлялись.

Проверка сохранения в базу целиком прогнана на PostgreSQL отдельно (тесты
здесь идут на sqlite, а сохранение использует возможности PostgreSQL);
здесь закреплены функции чтения, через которые теперь идут все такие поля.
"""

from decimal import Decimal

from app.repositories.repositories import (
    _visit_amount,
    _деньги,
    _записи,
    _словарь,
    _целое,
)


def test_вложенный_объект_null_это_пустой_словарь():
    assert _словарь(None) == {}
    assert _словарь("строка") == {}
    assert _словарь({"id": 5}) == {"id": 5}


def test_список_null_и_мусор_внутри():
    assert _записи(None) == []
    assert _записи([None, {"id": 1}, "x", 3]) == [{"id": 1}]


def test_деньги_из_null_и_мусора():
    assert _деньги(None) == Decimal("0")
    assert _деньги("") == Decimal("0")
    assert _деньги("не число") == Decimal("0")
    assert _деньги("1500.50") == Decimal("1500.50")
    assert _деньги(1800) == Decimal("1800")


def test_целое_из_null():
    assert _целое(None) == 0
    assert _целое("7") == 7
    assert _целое("мусор") == 0


def test_сумма_визита_при_null_в_услугах():
    assert _visit_amount(None) == Decimal("0")
    assert _visit_amount([None, {"cost": None, "cost_to_pay": None}]) == Decimal("0")
    assert _visit_amount([{"cost_to_pay": 1500, "cost": 1800}, None]) == Decimal("1500")


def test_запись_без_клиента_читается_как_в_28_09():
    """Ровно та запись, на которой встала выгрузка."""
    запись = {"id": 1, "client": None, "services": None, "paid_full": None}
    клиент = _словарь(запись.get("client"))
    assert _целое(клиент.get("id")) == 0
    assert _visit_amount(запись.get("services")) == Decimal("0")
    assert _деньги(запись.get("paid_full")) == Decimal("0")
