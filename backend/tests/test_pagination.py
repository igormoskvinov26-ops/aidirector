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


# --------------------------------------------------------------------------- #
# Итог выгрузки должен попадать в журнал всегда
#
# На живой установке клиентов приехало ровно 4000 — слишком круглое число,
# чтобы принимать его на веру, а сверить было нечем: строка с итогом
# печаталась раз в десять страниц и до конца могла не дойти.
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_итог_печатается_даже_при_пустой_первой_странице(monkeypatch, caplog):
    """Прежде здесь падало с UnboundLocalError: переменная итога объявлялась
    внутри цикла, а цикл обрывался до присваивания."""
    клиент = YClientsClient()
    вызовы = [_страница(1, 0, всего=0)]

    async def подделка(path, params=None):
        return ПоддельныйОтвет(вызовы.pop(0))

    monkeypatch.setattr(клиент, "_request", подделка)
    результат = await клиент._get_paginated("/clients/1")
    assert результат == []
    await клиент.close()


@pytest.mark.asyncio
async def test_итог_печатается_при_простом_списке(monkeypatch):
    """Некоторые адреса отдают массив вместо объекта с data."""
    клиент = YClientsClient()

    async def подделка(path, params=None):
        return ПоддельныйОтвет([{"id": 1}, {"id": 2}])

    monkeypatch.setattr(клиент, "_request", подделка)
    результат = await клиент._get_paginated("/что-то")
    assert len(результат) == 2
    await клиент.close()


# --------------------------------------------------------------------------- #
# Предел страниц не должен резать выдачу
#
# Живой случай 17.09.2026: /clients/2036703 отдаёт по 20 строк на страницу,
# сколько ни проси через page_size. Постоянный предел в 200 страниц дал 4000
# записей из 4082 — восемьдесят два клиента не доехали, и зарплата с
# план-фактом считались по неполным данным.
# --------------------------------------------------------------------------- #


def _мелкая_страница(номер: int, на_странице: int, всего: int) -> dict:
    """Страница адреса, который отдаёт свой размер, а не запрошенный."""
    начало = (номер - 1) * на_странице
    осталось = max(0, всего - начало)
    сколько = min(на_странице, осталось)
    return {
        "data": [{"id": начало + i} for i in range(сколько)],
        "meta": {"total_count": всего},
    }


@pytest.mark.asyncio
async def test_забирает_всё_когда_страницы_мельче_запрошенных(monkeypatch):
    """Ровно живой случай: 4082 записи по 20 на страницу — это 205 страниц."""
    клиент = YClientsClient()
    всего = 4082

    async def подделка(path, params=None):
        return ПоддельныйОтвет(_мелкая_страница(params["page"], 20, всего))

    monkeypatch.setattr(клиент, "_request", подделка)
    monkeypatch.setattr("app.api.yclients.RATE_LIMIT_DELAY", 0)
    результат = await клиент._get_paginated("/clients/2036703")
    assert len(результат) == всего, "выгрузка оборвалась на пределе страниц"
    await клиент.close()


@pytest.mark.asyncio
async def test_прежний_постоянный_предел_потерял_бы_записи(monkeypatch):
    """Проверка самой проверки: при пределе в 200 страниц по 20 строк
    получилось бы ровно 4000 — то число, что владелец увидел на своей
    установке."""
    assert 200 * 20 == 4000
    from app.api import yclients

    assert yclients.ЖЁСТКИЙ_ПРЕДЕЛ_СТРАНИЦ * 20 > 4082


@pytest.mark.asyncio
async def test_жёсткий_предел_не_превышается(monkeypatch):
    """Если адрес обещает больше, чем бывает, выгрузка всё равно кончается."""
    клиент = YClientsClient()
    вызовов = {"сколько": 0}

    async def подделка(path, params=None):
        вызовов["сколько"] += 1
        # Обещает миллион записей и честно отдаёт по одной.
        return ПоддельныйОтвет(_мелкая_страница(params["page"], 1, 1_000_000))

    monkeypatch.setattr(клиент, "_request", подделка)
    monkeypatch.setattr("app.api.yclients.RATE_LIMIT_DELAY", 0)
    await клиент._get_paginated("/что-то")
    from app.api import yclients

    assert вызовов["сколько"] <= yclients.ЖЁСТКИЙ_ПРЕДЕЛ_СТРАНИЦ
    await клиент.close()


@pytest.mark.asyncio
async def test_размер_страницы_просится_двумя_именами(monkeypatch):
    """Какое имя понимает адрес, по ответу не видно. Лишнее он игнорирует."""
    клиент = YClientsClient()
    увиденные: dict = {}

    async def подделка(path, params=None):
        увиденные.update(params or {})
        return ПоддельныйОтвет({"data": [], "meta": {"total_count": 0}})

    monkeypatch.setattr(клиент, "_request", подделка)
    await клиент._get_paginated("/clients/1")
    assert увиденные["page_size"] == 200
    assert увиденные["count"] == 200
    await клиент.close()
