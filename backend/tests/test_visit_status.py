"""Коды посещения YCLIENTS должны различать несостоявшийся визит и будущий.

Раньше отмены и неявки попадали в «запланировано». Неявка прошлой недели
навсегда оставалась будущим доходом: на графике её рисовало контуром как
запись, которая ещё принесёт деньги, и сумма запланированного росла от
каждого несостоявшегося визита.
"""

import pytest

from app.repositories.repositories import _normalize_visit_status


@pytest.mark.parametrize("raw", [1, "1", "completed", "finished", "attended", "visit"])
def test_attended_is_completed(raw):
    assert _normalize_visit_status(raw) == "completed"


@pytest.mark.parametrize("raw", [-1, "-1", "noshow", "no_show", "no show", "unattended"])
def test_no_show_is_not_scheduled(raw):
    """Клиент не пришёл — денег не будет. Это не будущая запись."""
    assert _normalize_visit_status(raw) == "no_show"


@pytest.mark.parametrize("raw", ["canceled", "cancelled", "deleted"])
def test_cancelled_is_not_scheduled(raw):
    assert _normalize_visit_status(raw) == "cancelled"


@pytest.mark.parametrize("raw", [0, "0", 2, "2", None, "", "unknown", "whatever"])
def test_waiting_and_confirmed_are_scheduled(raw):
    """Код 2 — подтверждена, 0 — ожидает. И то и другое ещё впереди."""
    assert _normalize_visit_status(raw) == "scheduled"


def test_every_status_is_one_of_four():
    """Ни один код не должен проваливаться в пятое состояние."""
    allowed = {"completed", "scheduled", "no_show", "cancelled"}
    for raw in (-1, 0, 1, 2, 3, 99, None, "", "мусор", [], {}):
        assert _normalize_visit_status(raw) in allowed
