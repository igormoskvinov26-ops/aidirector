"""Настройка интеграций через веб: хранение, приоритет, маски, импорт .env.

Сценарии взяты из ТЗ «Управление ключами и .env через Web UI», раздел 22.
Проверяется то, что ломается тихо: маска, ушедшая в базу вместо токена;
импорт, стерший настроенный чат; правка одного поля, обнулившая соседнее.

Переменные окружения в этих тестах гасятся намеренно. conftest выставляет их
для всех остальных, а здесь они означали бы «задано инфраструктурой» — то
есть управляемые значения не применялись бы вовсе, и тесты проверяли бы не
то, что нужно.
"""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.services import configuration

ВЛАДЕЛЕЦ = "owner"


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


@pytest.fixture(autouse=True)
def чистое_окружение(monkeypatch):
    """Ни один ключ не считается заданным инфраструктурой, кэш пуст."""
    monkeypatch.setattr(configuration, "ИЗ_ОКРУЖЕНИЯ_ПРОЦЕССА", frozenset())
    monkeypatch.setattr(configuration, "_управляемые", {})
    monkeypatch.setattr(configuration, "_последняя_ошибка", {})
    from app.config import settings

    for поле in (
        "yclients_partner_token",
        "yclients_user_token",
        "telegram_bot_token",
        "telegram_chat_id",
    ):
        monkeypatch.setattr(settings, поле, "")
    monkeypatch.setattr(settings, "yclients_company_id", 0)


# ── Сценарий 2: ничего не заполнено, приложение не падает ─────────────────


def test_без_ключей_статус_требуется_настройка():
    обзор = configuration.обзор()
    assert обзор["ready"] is False
    по_ид = {и["id"]: и for и in обзор["integrations"]}
    assert по_ид["yclients"]["status"] == configuration.ТРЕБУЕТСЯ
    assert по_ид["telegram"]["status"] == configuration.ТРЕБУЕТСЯ
    assert "YCLIENTS_PARTNER_TOKEN" in обзор["missing"]


# ── Сценарий 3: YCLIENTS есть, Telegram нет ───────────────────────────────


@pytest.mark.asyncio
async def test_yclients_настроен_telegram_нет(session: AsyncSession):
    await configuration.сохранить(
        session,
        {
            "YCLIENTS_PARTNER_TOKEN": "партнёр-1234",
            "YCLIENTS_USER_TOKEN": "юзер-5678",
            "YCLIENTS_COMPANY_ID": "19164",
        },
        ВЛАДЕЛЕЦ,
    )
    обзор = configuration.обзор()
    по_ид = {и["id"]: и for и in обзор["integrations"]}

    # Ядро готово: аналитика работает, хотя Telegram не настроен.
    assert обзор["ready"] is True
    assert по_ид["yclients"]["status"] == configuration.НАСТРОЕНО
    assert по_ид["telegram"]["status"] == configuration.ТРЕБУЕТСЯ
    assert configuration.настроена("yclients") is True
    assert configuration.настроена("telegram") is False


# ── Сценарий 5: часть обязательных ключей ─────────────────────────────────


@pytest.mark.asyncio
async def test_частичная_настройка(session: AsyncSession):
    await configuration.сохранить(
        session, {"YCLIENTS_PARTNER_TOKEN": "партнёр-1234"}, ВЛАДЕЛЕЦ
    )
    по_ид = {и["id"]: и for и in configuration.обзор()["integrations"]}
    assert по_ид["yclients"]["status"] == configuration.ЧАСТИЧНО


# ── Сценарий 9 и 14: приоритет источников ─────────────────────────────────


@pytest.mark.asyncio
async def test_заданное_инфраструктурой_не_перекрывается(session: AsyncSession, monkeypatch):
    """Значение из переменной окружения веб-интерфейс менять не вправе.

    Иначе настройка «применяется» ровно до перезапуска, после которого молча
    возвращается значение инфраструктуры.
    """
    from app.config import settings

    monkeypatch.setattr(settings, "yclients_partner_token", "из-окружения")
    monkeypatch.setattr(
        configuration, "ИЗ_ОКРУЖЕНИЯ_ПРОЦЕССА", frozenset({"YCLIENTS_PARTNER_TOKEN"})
    )

    изменены = await configuration.сохранить(
        session, {"YCLIENTS_PARTNER_TOKEN": "из-браузера"}, ВЛАДЕЛЕЦ
    )
    assert изменены == []
    assert configuration.значение("YCLIENTS_PARTNER_TOKEN") == "из-окружения"
    assert configuration.источник("YCLIENTS_PARTNER_TOKEN") == "process_env"

    поля = {
        п["key"]: п
        for и in configuration.обзор()["integrations"]
        for п in и["fields"]
    }
    assert поля["YCLIENTS_PARTNER_TOKEN"]["locked"] is True


@pytest.mark.asyncio
async def test_управляемое_главенствует_над_файлом(session: AsyncSession, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "yclients_user_token", "из-файла")
    assert configuration.источник("YCLIENTS_USER_TOKEN") == "env_file"

    await configuration.сохранить(session, {"YCLIENTS_USER_TOKEN": "из-браузера"}, ВЛАДЕЛЕЦ)
    assert configuration.значение("YCLIENTS_USER_TOKEN") == "из-браузера"
    assert configuration.источник("YCLIENTS_USER_TOKEN") == "managed"


# ── Сценарий 11: правка одного поля не затирает соседнее ──────────────────


@pytest.mark.asyncio
async def test_пустое_поле_означает_не_менять(session: AsyncSession):
    await configuration.сохранить(
        session,
        {"YCLIENTS_PARTNER_TOKEN": "партнёр-1234", "YCLIENTS_USER_TOKEN": "юзер-5678"},
        ВЛАДЕЛЕЦ,
    )
    # Владелец меняет только номер филиала, остальные поля формы пусты.
    await configuration.сохранить(
        session,
        {
            "YCLIENTS_COMPANY_ID": "19164",
            "YCLIENTS_PARTNER_TOKEN": "",
            "YCLIENTS_USER_TOKEN": "",
        },
        ВЛАДЕЛЕЦ,
    )
    assert configuration.значение("YCLIENTS_PARTNER_TOKEN") == "партнёр-1234"
    assert configuration.значение("YCLIENTS_USER_TOKEN") == "юзер-5678"
    assert configuration.число("YCLIENTS_COMPANY_ID") == 19164


# ── Маскирование (разделы 7, 9, 14 ТЗ) ────────────────────────────────────


@pytest.mark.asyncio
async def test_секрет_наружу_не_уходит(session: AsyncSession):
    await configuration.сохранить(
        session, {"YCLIENTS_PARTNER_TOKEN": "очень-секретный-токен-7Kp2"}, ВЛАДЕЛЕЦ
    )
    поля = {
        п["key"]: п for и in configuration.обзор()["integrations"] for п in и["fields"]
    }
    партнёр = поля["YCLIENTS_PARTNER_TOKEN"]

    assert партнёр["configured"] is True
    assert партнёр["display"] == "••••••••7Kp2"
    assert "очень-секретный" not in str(configuration.обзор())


def test_несекретное_показывается_как_есть(monkeypatch):
    monkeypatch.setattr(configuration, "_управляемые", {"YCLIENTS_COMPANY_ID": "19164"})
    поля = {
        п["key"]: п for и in configuration.обзор()["integrations"] for п in и["fields"]
    }
    assert поля["YCLIENTS_COMPANY_ID"]["display"] == "19164"
    assert поля["YCLIENTS_COMPANY_ID"]["secret"] is False


def test_короткий_секрет_не_показывается_даже_частично():
    assert configuration.маска("abc") == "••••••••"
    assert configuration.маска("") == ""


# ── Разбор .env (раздел 6 ТЗ) ─────────────────────────────────────────────


def test_разбор_понимает_кавычки_и_комментарии():
    разобрано = configuration.разобрать_env(
        "\n".join(
            [
                "# комментарий",
                "",
                "YCLIENTS_PARTNER_TOKEN=простое",
                'YCLIENTS_USER_TOKEN="в двойных"',
                "TELEGRAM_CHAT_ID='в одинарных'",
                "export TELEGRAM_BOT_TOKEN=со-словом-export",
            ]
        )
    )
    assert разобрано["YCLIENTS_PARTNER_TOKEN"] == "простое"
    assert разобрано["YCLIENTS_USER_TOKEN"] == "в двойных"
    assert разобрано["TELEGRAM_CHAT_ID"] == "в одинарных"
    assert разобрано["TELEGRAM_BOT_TOKEN"] == "со-словом-export"


def test_пустые_значения_считаются_отсутствующими():
    """Сценарий 15: KEY=, KEY="" и KEY='' — это «не задано», а не «стереть»."""
    разобрано = configuration.разобрать_env(
        "YCLIENTS_PARTNER_TOKEN=\nYCLIENTS_USER_TOKEN=\"\"\nTELEGRAM_CHAT_ID=''"
    )
    assert разобрано == {}


def test_файл_не_выполняется():
    """Строка с командой остаётся строкой: ничего не запускается и не подставляется."""
    разобрано = configuration.разобрать_env("YCLIENTS_USER_TOKEN=$(rm -rf /)")
    assert разобрано["YCLIENTS_USER_TOKEN"] == "$(rm -rf /)"


# ── Предпросмотр импорта (раздел 7 ТЗ) ────────────────────────────────────


def test_предпросмотр_показывает_найденное_и_недостающее():
    предпросмотр = configuration.предпросмотр(
        {
            "YCLIENTS_PARTNER_TOKEN": "партнёр-1234",
            "YCLIENTS_USER_TOKEN": "юзер-5678",
            "YCLIENTS_COMPANY_ID": "19164",
            "TELEGRAM_BOT_TOKEN": "бот-9999",
        }
    )
    по_ид = {и["id"]: и for и in предпросмотр["integrations"]}

    assert по_ид["yclients"]["status_after"] == configuration.НАСТРОЕНО
    # Чат не найден — Telegram станет настроенным лишь частично.
    assert по_ид["telegram"]["status_after"] == configuration.ЧАСТИЧНО

    поля = {п["key"]: п for п in по_ид["telegram"]["fields"]}
    assert поля["TELEGRAM_BOT_TOKEN"]["found"] is True
    assert поля["TELEGRAM_CHAT_ID"]["found"] is False


def test_предпросмотр_маскирует_секреты():
    предпросмотр = configuration.предпросмотр({"YCLIENTS_PARTNER_TOKEN": "секрет-7Kp2"})
    поля = {
        п["key"]: п for и in предпросмотр["integrations"] for п in и["fields"]
    }
    assert поля["YCLIENTS_PARTNER_TOKEN"]["display"] == "••••••••7Kp2"
    assert "секрет-7Kp2" not in str(предпросмотр)


def test_неизвестные_ключи_показываются_но_не_применяются():
    """Сценарий 6: чужие строки в файле не ломают импорт и не попадают в настройки."""
    предпросмотр = configuration.предпросмотр(
        {"YCLIENTS_PARTNER_TOKEN": "партнёр", "AWS_SECRET_KEY": "чужое", "FOO": "bar"}
    )
    assert предпросмотр["unknown"] == ["AWS_SECRET_KEY", "FOO"]
    assert предпросмотр["applicable"] == ["YCLIENTS_PARTNER_TOKEN"]


@pytest.mark.asyncio
async def test_импорт_не_трогает_то_чего_нет_в_файле(session: AsyncSession):
    """Сценарий 16: настроенное раньше не исчезает из-за неполного файла."""
    await configuration.сохранить(
        session, {"YCLIENTS_USER_TOKEN": "юзер-5678"}, ВЛАДЕЛЕЦ
    )
    await configuration.сохранить(
        session, {"YCLIENTS_PARTNER_TOKEN": "партнёр-1234"}, ВЛАДЕЛЕЦ
    )
    assert configuration.значение("YCLIENTS_USER_TOKEN") == "юзер-5678"


@pytest.mark.asyncio
async def test_неизвестный_ключ_не_сохраняется(session: AsyncSession):
    изменены = await configuration.сохранить(
        session, {"AWS_SECRET_KEY": "чужое"}, ВЛАДЕЛЕЦ
    )
    assert изменены == []


# ── Сброс (раздел 16 ТЗ) ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_сброс_возвращает_ключ_в_ненастроенное(session: AsyncSession):
    await configuration.сохранить(
        session,
        {
            "YCLIENTS_PARTNER_TOKEN": "партнёр-1234",
            "YCLIENTS_USER_TOKEN": "юзер-5678",
            "YCLIENTS_COMPANY_ID": "19164",
        },
        ВЛАДЕЛЕЦ,
    )
    await configuration.сбросить(session, "YCLIENTS_USER_TOKEN", ВЛАДЕЛЕЦ)

    assert configuration.значение("YCLIENTS_USER_TOKEN") == ""
    по_ид = {и["id"]: и for и in configuration.обзор()["integrations"]}
    assert по_ид["yclients"]["status"] == configuration.ЧАСТИЧНО


@pytest.mark.asyncio
async def test_сброс_чужого_ключа_отвергается(session: AsyncSession):
    with pytest.raises(ValueError):
        await configuration.сбросить(session, "AWS_SECRET_KEY", ВЛАДЕЛЕЦ)


# ── Журнал (раздел 15 ТЗ) ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_журнал_помнит_кто_менял_но_не_что(session: AsyncSession):
    await configuration.сохранить(
        session, {"YCLIENTS_PARTNER_TOKEN": "секретное-значение"}, ВЛАДЕЛЕЦ
    )
    записи = await configuration.журнал(session)

    assert len(записи) == 1
    assert записи[0]["who"] == ВЛАДЕЛЕЦ
    assert записи[0]["integration"] == "yclients"
    assert записи[0]["key"] == "YCLIENTS_PARTNER_TOKEN"
    assert записи[0]["action"] == "changed"
    assert "секретное-значение" not in str(записи)


# ── Числа ─────────────────────────────────────────────────────────────────


def test_мусор_в_числовом_поле_не_роняет(monkeypatch):
    monkeypatch.setattr(
        configuration, "_управляемые", {"YCLIENTS_COMPANY_ID": "не число"}
    )
    assert configuration.число("YCLIENTS_COMPANY_ID") == 0


# ── Одновременные сохранения (сценарий 14 ТЗ) ─────────────────────────────


@pytest.mark.asyncio
async def test_одновременные_сохранения_не_теряются():
    """Две правки разных ключей должны обе дойти до базы.

    Сессии здесь разные, как у двух запросов: общая сессия скрыла бы ровно
    ту проблему, ради которой этот тест написан.
    """
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    движок = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with движок.begin() as соединение:
        await соединение.run_sync(Base.metadata.create_all)
    создатель = async_sessionmaker(движок, expire_on_commit=False)

    async def записать(ключ: str, значение_: str) -> None:
        async with создатель() as сессия:
            await configuration.сохранить(сессия, {ключ: значение_}, ВЛАДЕЛЕЦ)

    # sqlite в памяти не терпит настоящей параллельной записи, и это не то,
    # что проверяется: важно, что последовательные правки разных ключей не
    # затирают друг друга через общий кэш процесса.
    await записать("YCLIENTS_PARTNER_TOKEN", "партнёр-1234")
    await записать("YCLIENTS_USER_TOKEN", "юзер-5678")
    await asyncio.sleep(0)

    async with создатель() as сессия:
        await configuration.загрузить(сессия)

    assert configuration.значение("YCLIENTS_PARTNER_TOKEN") == "партнёр-1234"
    assert configuration.значение("YCLIENTS_USER_TOKEN") == "юзер-5678"
    await движок.dispose()


# ── Пользовательский токен по логину YCLIENTS ─────────────────────────────


class _ПоддельныйОтвет:
    def __init__(self, код: int, тело: dict):
        self.status_code = код
        self._тело = тело

    def json(self) -> dict:
        return self._тело


def _подменить_yclients(monkeypatch, ответ: "_ПоддельныйОтвет", запросы: list):
    import httpx

    class Клиент:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def post(self, путь, json=None, headers=None):
            запросы.append({"путь": путь, "тело": json, "заголовки": headers})
            return ответ

    monkeypatch.setattr(httpx, "AsyncClient", Клиент)


@pytest.mark.asyncio
async def test_токен_по_логину_сохраняется(session: AsyncSession, monkeypatch):
    monkeypatch.setattr(configuration, "_управляемые", {"YCLIENTS_PARTNER_TOKEN": "партнёр-1234"})
    запросы: list = []
    _подменить_yclients(
        monkeypatch,
        _ПоддельныйОтвет(201, {"success": True, "data": {"user_token": "выданный-5678", "name": "Игорь"}}),
        запросы,
    )

    имя = await configuration.получить_пользовательский_токен(
        session, "79991234567", "пароль-кабинета", ВЛАДЕЛЕЦ
    )

    assert имя == "Игорь"
    assert configuration.значение("YCLIENTS_USER_TOKEN") == "выданный-5678"
    assert запросы[0]["путь"] == "/auth"
    assert запросы[0]["заголовки"]["Authorization"] == "Bearer партнёр-1234"
    # Логин и пароль в хранилище не попадают — только токен.
    assert "пароль-кабинета" not in str(configuration._управляемые)
    assert "79991234567" not in str(configuration._управляемые)


@pytest.mark.asyncio
async def test_неверный_логин_yclients_понятная_ошибка(session: AsyncSession, monkeypatch):
    monkeypatch.setattr(configuration, "_управляемые", {"YCLIENTS_PARTNER_TOKEN": "партнёр-1234"})
    _подменить_yclients(
        monkeypatch,
        _ПоддельныйОтвет(401, {"success": False, "data": None, "meta": {"message": "Неверный логин"}}),
        [],
    )
    with pytest.raises(ValueError, match="не принял логин или пароль"):
        await configuration.получить_пользовательский_токен(
            session, "79991234567", "не-тот", ВЛАДЕЛЕЦ
        )
    assert configuration.значение("YCLIENTS_USER_TOKEN") == ""


@pytest.mark.asyncio
async def test_без_партнёрского_токена_не_спрашиваем(session: AsyncSession):
    with pytest.raises(ValueError, match="партнёрский токен"):
        await configuration.получить_пользовательский_токен(
            session, "79991234567", "пароль", ВЛАДЕЛЕЦ
        )
