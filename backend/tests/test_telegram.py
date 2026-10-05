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

    async def get(self, *_, **__):
        raise self._исключение


class _УспешныйКлиент:
    """Замена httpx.AsyncClient, отвечающая заданным JSON на любой запрос."""

    def __init__(self, тело: dict, статус: int = 200, *_, **__):
        self._тело = тело
        self._статус = статус

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def get(self, *_, **__):
        return httpx.Response(self._статус, json=self._тело)

    async def post(self, *_, **__):
        return httpx.Response(self._статус, json=self._тело)


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


# --------------------------------------------------------------------------- #
# Форма «Настройка ТГ»: узнать бота, найти чаты, проверить конкретный chat_id
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_узнать_бота_возвращает_имя(monkeypatch):
    import app.services.telegram as telegram

    результат = {"username": "rubl_bot", "id": 111}
    monkeypatch.setattr(
        telegram.httpx,
        "AsyncClient",
        lambda *a, **kw: _УспешныйКлиент({"ok": True, "result": результат}),
    )
    итог = await telegram.узнать_бота("любой-токен")
    assert итог == {"username": "rubl_bot", "id": 111}


@pytest.mark.asyncio
async def test_узнать_бота_отклонённый_токен(monkeypatch):
    import app.services.telegram as telegram

    monkeypatch.setattr(
        telegram.httpx,
        "AsyncClient",
        lambda *a, **kw: _УспешныйКлиент({"ok": False}, статус=401),
    )
    with pytest.raises(TelegramSendError, match="скопирован целиком"):
        await telegram.узнать_бота("плохой-токен")


@pytest.mark.asyncio
async def test_найти_чаты_разбирает_getupdates_и_не_дублирует(monkeypatch):
    import app.services.telegram as telegram

    monkeypatch.setattr(
        telegram.httpx,
        "AsyncClient",
        lambda *a, **kw: _УспешныйКлиент({"ok": True, "result": [
            {"update_id": 1, "message": {"chat": {"id": -100123, "title": "РублЪ Пульт"}}},
            {"update_id": 2, "message": {"chat": {"id": -100123, "title": "РублЪ Пульт"}}},
        ]}),
    )
    чаты = await telegram.найти_чаты("токен")
    assert чаты == [{"chat_id": -100123, "title": "РублЪ Пульт"}]


@pytest.mark.asyncio
async def test_найти_чаты_без_обновлений_пустой_список(monkeypatch):
    import app.services.telegram as telegram

    monkeypatch.setattr(
        telegram.httpx, "AsyncClient", lambda *a, **kw: _УспешныйКлиент({"ok": True, "result": []})
    )
    assert await telegram.найти_чаты("токен") == []


@pytest.mark.asyncio
async def test_проверить_чат_возвращает_название(monkeypatch):
    import app.services.telegram as telegram

    monkeypatch.setattr(
        telegram.httpx,
        "AsyncClient",
        lambda *a, **kw: _УспешныйКлиент({"ok": True, "result": {"title": "РублЪ Пульт"}}),
    )
    итог = await telegram.проверить_чат("токен", "-100123")
    assert итог == {"title": "РублЪ Пульт"}


@pytest.mark.asyncio
async def test_проверить_чат_не_найден(monkeypatch):
    import app.services.telegram as telegram

    monkeypatch.setattr(
        telegram.httpx, "AsyncClient", lambda *a, **kw: _УспешныйКлиент({"ok": False}, статус=400)
    )
    with pytest.raises(TelegramSendError, match="не нашёл этот чат"):
        await telegram.проверить_чат("токен", "-999")


@pytest.mark.asyncio
async def test_отправка_предпочитает_настройки_из_базы(monkeypatch):
    """Если владелец настроил Telegram в интерфейсе, .env больше не используется."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    import app.services.telegram as telegram
    from app.database import Base
    from app.services import telegram_settings

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session = async_sessionmaker(engine, expire_on_commit=False)()
    await telegram_settings.сохранить(
        session, bot_token="db-токен", chat_id="db-чат", bot_username="bot", chat_title="Чат"
    )

    увиденные_запросы: list[tuple] = []

    class _Клиент:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def post(self, url, data):
            увиденные_запросы.append((url, data))
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    monkeypatch.setattr(telegram.httpx, "AsyncClient", lambda *a, **kw: _Клиент())

    await telegram.отправить_сообщение("текст", session)
    await engine.dispose()

    [(url, data)] = увиденные_запросы
    assert "bot" + "db-токен" in url
    assert data["chat_id"] == "db-чат"
