"""Настройка Telegram на странице «Смена»: хранение и приоритет над .env.

Решение владельца 27.09.2026. Строка в базе — единственная и главенствует
над TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID из .env, когда она есть; если
владелец форму ещё не открывал, всё продолжает работать на .env — иначе у
уже развёрнутых установок Telegram отвалился бы сам собой.
"""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.services import telegram_settings


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_без_настройки_в_базе_подставляется_env(session: AsyncSession):
    токен, чат = await telegram_settings.учётные_данные(session, "env-токен", "env-чат")
    assert (токен, чат) == ("env-токен", "env-чат")

    словарь = await telegram_settings.как_словарь(session, "env-токен", "env-чат")
    assert словарь["configured"] is True
    assert словарь["source"] == "env"
    assert словарь["bot_token_masked"] == "…окен"


@pytest.mark.asyncio
async def test_без_настройки_и_без_env_не_настроено(session: AsyncSession):
    словарь = await telegram_settings.как_словарь(session, "", "")
    assert словарь == {
        "configured": False, "source": "none", "bot_username": None,
        "bot_token_masked": None, "chat_id": None, "chat_title": None, "updated_at": None,
    }


@pytest.mark.asyncio
async def test_настройка_в_базе_главенствует_над_env(session: AsyncSession):
    await telegram_settings.сохранить(
        session, bot_token="db-токен-1234", chat_id="-100999",
        bot_username="rubl_bot", chat_title="РублЪ Директор",
    )

    токен, чат = await telegram_settings.учётные_данные(session, "env-токен", "env-чат")
    assert (токен, чат) == ("db-токен-1234", "-100999")

    словарь = await telegram_settings.как_словарь(session, "env-токен", "env-чат")
    assert словарь["configured"] is True
    assert словарь["source"] == "database"
    assert словарь["bot_username"] == "rubl_bot"
    assert словарь["chat_title"] == "РублЪ Директор"
    assert словарь["bot_token_masked"] == "…1234"
    assert "db-токен" not in словарь["bot_token_masked"]


@pytest.mark.asyncio
async def test_повторное_сохранение_затирает_старое(session: AsyncSession):
    await telegram_settings.сохранить(
        session, bot_token="токен-раз", chat_id="1", bot_username="bot1", chat_title="Чат 1"
    )
    await telegram_settings.сохранить(
        session, bot_token="токен-два", chat_id="2", bot_username="bot2", chat_title="Чат 2"
    )

    настройки = await telegram_settings.получить(session)
    assert настройки.bot_token == "токен-два"
    assert настройки.chat_id == "2"
    assert настройки.chat_title == "Чат 2"
