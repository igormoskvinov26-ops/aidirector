"""Отказ YCLIENTS объясняется его же словами, а проверка связи называет филиалы токена."""

import httpx
import pytest

from app.api import yclients
from app.services import configuration


def _mock(handler, monkeypatch):
    настоящий = httpx.AsyncClient

    def фабрика(*a, **k):
        return настоящий(*a, transport=httpx.MockTransport(handler), **k)

    monkeypatch.setattr(yclients.httpx, "AsyncClient", фабрика)
    ключи = {"YCLIENTS_PARTNER_TOKEN": "p", "YCLIENTS_USER_TOKEN": "u", "YCLIENTS_COMPANY_ID": "2036703"}
    monkeypatch.setattr(configuration, "значение", lambda имя: ключи.get(имя, ""))
    monkeypatch.setattr(configuration, "число", lambda имя: int(ключи.get(имя, 0) or 0))


@pytest.mark.asyncio
async def test_403_shows_yclients_reason_and_accessible_branches(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/companies"):
            return httpx.Response(200, json={"success": True, "data": [{"id": 111, "title": "РублЪ старый"}]})
        return httpx.Response(403, json={"success": False, "meta": {"message": "Нет прав на филиал"}})

    _mock(handler, monkeypatch)
    with pytest.raises(RuntimeError) as e:
        await configuration._проверить_yclients()
    текст = str(e.value)
    assert "Нет прав на филиал" in текст and "403" in текст
    assert "111 «РублЪ старый»" in текст and "2036703" in текст


@pytest.mark.asyncio
async def test_sync_error_text_carries_reason(monkeypatch):
    _mock(lambda r: httpx.Response(403, json={"meta": {"message": "Партнёр не авторизован"}}), monkeypatch)
    async with yclients.YClientsClient() as клиент:
        with pytest.raises(httpx.HTTPStatusError) as e:
            await клиент.get_staff()
    assert "Партнёр не авторизован" in str(e.value) and "Client error" not in str(e.value)
