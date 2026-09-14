"""Выгрузка страниц не должна обрываться молча.

YCLIENTS отдаёт по 50 строк, сколько ни проси, и по /transactions/ не
присылает total_count. Прежняя версия считала короткую страницу последней и
забирала первые 50 записей из нескольких сотен — без ошибки, просто меньше
данных. На этих числах считается зарплата мастеров.
"""

import httpx
import pytest

from app.api.yclients import YClientsClient


class ПоддельныйОтвет:
    def __init__(self, тело):
        self._тело = тело

    def json(self):
        return self._тело


def _страница(номер: int, сколько: int, всего: int | None = None) -> dict:
    начало = (номер - 1) * 50
    тело = {"data": [{"id": начало + i} for i in range(сколько)]}
    if всего is not None:
        тело["meta"] = {"total_count": всего}
    return тело


@pytest.fixture
def client():
    return YClientsClient(company_id=1, user_token="t")


@pytest.mark.asyncio
async def test_short_pages_are_not_treated_as_the_last(client, monkeypatch):
    """Сервер отдаёт по 50 при запросе 200 — это не признак конца."""
    страницы = {1: _страница(1, 50), 2: _страница(2, 50), 3: _страница(3, 17), 4: {"data": []}}
    запрошено = []

    async def поддельный_запрос(path, params=None):
        запрошено.append(params["page"])
        return ПоддельныйОтвет(страницы[params["page"]])

    monkeypatch.setattr(client, "_request", поддельный_запрос)
    monkeypatch.setattr("app.api.yclients.RATE_LIMIT_DELAY", 0)

    строки = await client._get_paginated("/transactions/1")

    assert len(строки) == 117
    assert запрошено == [1, 2, 3, 4]


@pytest.mark.asyncio
async def test_total_count_still_stops_the_walk(client, monkeypatch):
    """Где total_count есть, лишнюю страницу дёргать незачем."""
    страницы = {1: _страница(1, 50, всего=80), 2: _страница(2, 30, всего=80)}
    запрошено = []

    async def поддельный_запрос(path, params=None):
        запрошено.append(params["page"])
        return ПоддельныйОтвет(страницы[params["page"]])

    monkeypatch.setattr(client, "_request", поддельный_запрос)
    monkeypatch.setattr("app.api.yclients.RATE_LIMIT_DELAY", 0)

    строки = await client._get_paginated("/records/1")

    assert len(строки) == 80
    assert запрошено == [1, 2]


@pytest.mark.asyncio
async def test_a_page_that_repeats_itself_stops_the_walk(client, monkeypatch):
    """Адрес, не понимающий page, отдаёт одно и то же — не набивать повторами."""
    запрошено = []

    async def поддельный_запрос(path, params=None):
        запрошено.append(params["page"])
        return ПоддельныйОтвет(_страница(1, 50))

    monkeypatch.setattr(client, "_request", поддельный_запрос)
    monkeypatch.setattr("app.api.yclients.RATE_LIMIT_DELAY", 0)

    строки = await client._get_paginated("/transactions/1")

    assert len(строки) == 50
    assert запрошено == [1, 2]


@pytest.mark.asyncio
async def test_empty_first_page_returns_nothing(client, monkeypatch):
    async def поддельный_запрос(path, params=None):
        return ПоддельныйОтвет({"data": []})

    monkeypatch.setattr(client, "_request", поддельный_запрос)
    assert await client._get_paginated("/transactions/1") == []


@pytest.mark.asyncio
async def test_a_plain_list_answer_is_taken_as_is(client, monkeypatch):
    """Часть адресов отвечает списком без обёртки — страниц там нет."""
    async def поддельный_запрос(path, params=None):
        return ПоддельныйОтвет([{"id": 1}, {"id": 2}])

    monkeypatch.setattr(client, "_request", поддельный_запрос)
    assert len(await client._get_paginated("/x")) == 2


@pytest.mark.asyncio
async def test_real_client_is_closed_after_the_test(client):
    """Хвост: клиент httpx закрывается, иначе тесты сыплют предупреждениями."""
    assert isinstance(client._client, httpx.AsyncClient)
    await client.close()
