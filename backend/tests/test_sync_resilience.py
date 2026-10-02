"""Отказ одного шага выгрузки не должен отменять остальные.

До правки выгрузка была «всё или ничего»: сотрудники идут первым шагом, и
любой их отказ обрывал прогон целиком — визиты и продажи не обновлялись,
хотя могли бы. Плюс в сообщении не было ни шага, ни адреса: владелец видел
голое ``'NoneType' object is not iterable``.
"""

from typing import Any

import pytest

from app.services import sync


class ПоддельныйКлиент:
    """Клиент YCLIENTS, который отвечает заготовками и умеет падать.

    ``падает`` — набор имён методов, которые должны поднять исключение.
    """

    def __init__(self, падает: set[str] | None = None, пустые: set[str] | None = None):
        self.падает = падает or set()
        self.пустые = пустые or set()
        self.вызвано: list[str] = []

    async def __aenter__(self) -> "ПоддельныйКлиент":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    def _ответ(self, имя: str, заготовка: list[dict]) -> list[dict]:
        self.вызвано.append(имя)
        if имя in self.падает:
            raise RuntimeError(f"{имя}: адрес ответил отказом")
        if имя in self.пустые:
            return []
        return заготовка

    async def get_staff(self) -> list[dict]:
        return self._ответ("staff", [{"id": 1, "name": "Арташ"}])

    async def get_services(self) -> list[dict]:
        return self._ответ("services", [{"id": 10, "title": "Стрижка"}])

    async def get_all_clients(self) -> list[dict]:
        return self._ответ("clients", [{"id": 100}])

    async def get_all_records(self, date_from: str, date_to: str) -> list[dict]:
        return self._ответ("visits", [{"id": 1000}])

    async def get_transactions(self, date_from: str, date_to: str) -> list[dict]:
        return self._ответ("sales", [{"id": 5, "good": {"id": 7}}])


class ПоддельнаяСессия:
    async def __aenter__(self) -> "ПоддельнаяСессия":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


class ПоддельныйРепозиторий:
    """Считает строки и ничего не пишет. Отдаёт число — как настоящие."""

    @staticmethod
    async def upsert_many(session: Any, data: list[dict], *args: Any) -> int:
        return len(data or [])

    @staticmethod
    async def get_all(session: Any) -> list:
        return []


class ПоддельныйРепозиторийСотрудников(ПоддельныйРепозиторий):
    """Сотрудники возвращают список идентификаторов, а не число."""

    @staticmethod
    async def upsert_many(session: Any, data: list[dict], *args: Any) -> list[int]:
        return list(range(len(data or [])))


@pytest.fixture
def стенд(monkeypatch):
    """Подменяет всё внешнее и возвращает копилку записанных прогонов."""
    прогоны: list[dict] = []

    async def записать(начало, статистика, ошибка):
        прогоны.append({"статистика": dict(статистика), "ошибка": ошибка})

    monkeypatch.setattr(sync, "async_session", ПоддельнаяСессия)
    monkeypatch.setattr(sync, "_записать_прогон", записать)
    monkeypatch.setattr(sync, "EmployeeRepository", ПоддельныйРепозиторийСотрудников)
    for имя in (
        "ServiceRepository",
        "ClientRepository",
        "VisitRepository",
        "ProductRepository",
        "SaleRepository",
    ):
        monkeypatch.setattr(sync, имя, ПоддельныйРепозиторий)
    monkeypatch.setattr(sync.cache, "invalidate", lambda *_a, **_k: 0)
    monkeypatch.setattr(sync, "_sync_in_progress", False)
    return прогоны


def поставить_клиент(monkeypatch, клиент: ПоддельныйКлиент) -> None:
    monkeypatch.setattr(sync, "YClientsClient", lambda *a, **k: клиент)


@pytest.mark.asyncio
async def test_удачная_выгрузка_проходит_все_шаги(monkeypatch, стенд):
    клиент = ПоддельныйКлиент()
    поставить_клиент(monkeypatch, клиент)

    итог = await sync.sync_all()

    assert итог.get("error") is None
    assert стенд[-1]["ошибка"] is None
    assert {"staff", "services", "clients", "visits", "sales"} <= set(итог)


@pytest.mark.asyncio
async def test_отказ_сотрудников_не_отменяет_визиты_и_продажи(monkeypatch, стенд):
    """Главная проверка инцидента: первый шаг упал — остальные всё равно идут."""
    клиент = ПоддельныйКлиент(падает={"staff"})
    поставить_клиент(monkeypatch, клиент)

    итог = await sync.sync_all()

    assert "visits" in клиент.вызвано, "визиты не запрашивались после отказа сотрудников"
    assert "sales" in клиент.вызвано, "продажи не запрашивались"
    assert итог.get("visits") == 1
    assert итог.get("sales") == 1


@pytest.mark.asyncio
async def test_ошибка_называет_шаг(monkeypatch, стенд):
    """По тексту должно быть видно, что подвели именно сотрудники."""
    поставить_клиент(monkeypatch, ПоддельныйКлиент(падает={"staff"}))

    итог = await sync.sync_all()

    assert "сотрудники" in итог["error"]
    assert стенд[-1]["ошибка"] and "сотрудники" in стенд[-1]["ошибка"]


@pytest.mark.asyncio
async def test_пустой_список_сотрудников_это_отказ(monkeypatch, стенд):
    """Ноль сотрудников — признак отозванного токена, а не «нет изменений»."""
    поставить_клиент(monkeypatch, ПоддельныйКлиент(пустые={"staff"}))

    итог = await sync.sync_all()

    assert "сотрудники" in итог["error"]
    assert "токен" in итог["error"]


@pytest.mark.asyncio
async def test_прогон_помечается_неудачным_при_частичной_выгрузке(monkeypatch, стенд):
    """Частично привезли — это не успех: цифры на экране неполные."""
    поставить_клиент(monkeypatch, ПоддельныйКлиент(падает={"sales"}))

    await sync.sync_all()

    assert стенд[-1]["ошибка"] is not None
    assert "продажи" in стенд[-1]["ошибка"]


@pytest.mark.asyncio
async def test_несколько_отказов_перечисляются(monkeypatch, стенд):
    поставить_клиент(monkeypatch, ПоддельныйКлиент(падает={"staff", "sales"}))

    итог = await sync.sync_all()

    assert "сотрудники" in итог["error"]
    assert "продажи" in итог["error"]
