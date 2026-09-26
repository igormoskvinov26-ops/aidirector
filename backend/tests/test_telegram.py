"""Отправка в Telegram: сетевые сбои должны быть понятной ошибкой, не 500.

До этого теста обрыв сети или таймаут при обращении к api.telegram.org
поднимался наверх нераспознанным исключением, и с точки зрения кнопки
«Отправить в Telegram» это выглядело как «просто не работает» — без единого
слова о причине.
"""

import httpx
import pytest

from app.services.telegram import TelegramSendError, отправить_сообщение


class _ПадающийКлиент:
    """Замена httpx.AsyncClient, которая роняет запрос нужным исключением."""

    def __init__(self, исключение: Exception, *_, **__):
        self._исключение = исключение

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def post(self, *_, **__):
        raise self._исключение


@pytest.fixture(autouse=True)
def _настроен_telegram(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "telegram_bot_token", "test-token")
    monkeypatch.setattr(settings, "telegram_chat_id", "12345")


@pytest.mark.asyncio
async def test_таймаут_сети_даёт_понятную_ошибку(monkeypatch):
    import app.services.telegram as telegram

    monkeypatch.setattr(
        telegram.httpx,
        "AsyncClient",
        lambda *a, **kw: _ПадающийКлиент(httpx.TimeoutException("timed out"), *a, **kw),
    )
    with pytest.raises(TelegramSendError, match="не ответил вовремя"):
        await отправить_сообщение("текст")


@pytest.mark.asyncio
async def test_обрыв_сети_даёт_понятную_ошибку(monkeypatch):
    import app.services.telegram as telegram

    monkeypatch.setattr(
        telegram.httpx,
        "AsyncClient",
        lambda *a, **kw: _ПадающийКлиент(httpx.ConnectError("no route"), *a, **kw),
    )
    with pytest.raises(TelegramSendError, match="интернет-соединение"):
        await отправить_сообщение("текст")
