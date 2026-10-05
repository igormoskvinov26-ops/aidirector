"""Автосоздание учётной записи top из временного файла при обновлении.

Нужно само собой отработать на компьютере в салоне, без похода в Настройки:
установщик кладёт рядом файл с LOGIN=/PASSWORD=, приложение при старте
заводит top и сразу стирает файл, чтобы пароль не лежал на диске.
"""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.services import credentials


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
def без_учётных(monkeypatch):
    monkeypatch.setattr(credentials, "_учётные", {})


async def test_заводит_top_и_стирает_файл(session, tmp_path):
    файл = tmp_path / "top-seed.env"
    файл.write_text("LOGIN=Imosk\nPASSWORD=M@estro71\n", encoding="utf-8")

    await credentials.посеять_top_из_файла(session, str(файл))

    assert credentials.заведён("top")
    assert credentials.логин("top") == "Imosk"
    assert credentials.проверить_пароль("top", "Imosk", "M@estro71")
    assert not файл.exists()


async def test_не_трогает_уже_заведённый_top(session, tmp_path, monkeypatch):
    monkeypatch.setattr(
        credentials,
        "_учётные",
        {"TOP_LOGIN": "старый", "TOP_PASSWORD_HASH": credentials._хеш("старый-пароль-123")},
    )
    файл = tmp_path / "top-seed.env"
    файл.write_text("LOGIN=новый\nPASSWORD=новый-пароль-456\n", encoding="utf-8")

    await credentials.посеять_top_из_файла(session, str(файл))

    # top уже был — файл не тронут, старая запись не перезаписана.
    assert credentials.логин("top") == "старый"
    assert файл.exists()


async def test_без_файла_ничего_не_падает(session, tmp_path):
    await credentials.посеять_top_из_файла(session, str(tmp_path / "нет-такого.env"))
    assert not credentials.заведён("top")
