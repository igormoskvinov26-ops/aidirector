"""Первый запуск без .env: приложение поднимается и даёт себя настроить.

До этой доработки свежая установка означала тупик: чтобы открыть Директора,
нужен пароль из .env, а чтобы его туда вписать — доступ к файлу на сервере.
Проверяется, что тупика больше нет и что открытая на время настройки дверь
закрывается сразу, как только владелец заведён.
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
    monkeypatch.setattr(credentials, "_код", "")


@pytest.fixture
def пустой_env(monkeypatch):
    """Ни одной учётной записи в .env — как на свежей установке."""
    from app.config import settings

    for поле in ("owner_login", "owner_password", "operator_login", "operator_password"):
        monkeypatch.setattr(settings, поле, "")
    monkeypatch.setattr(settings, "master_accounts", [])


# ── Режим первичной настройки ─────────────────────────────────────────────


def test_без_владельца_нужна_настройка(пустой_env):
    from app.main import настройка_не_закончена

    assert настройка_не_закончена() is True


def test_владелец_из_env_снимает_режим_настройки(monkeypatch):
    from app.main import настройка_не_закончена

    assert настройка_не_закончена() is False


@pytest.mark.asyncio
async def test_заведённый_владелец_снимает_режим_настройки(
    session: AsyncSession, пустой_env
):
    from app.main import настройка_не_закончена

    assert настройка_не_закончена() is True
    await credentials.завести(session, "owner", "igor", "длинный-пароль-владельца")
    assert настройка_не_закончена() is False


# ── Код первичной настройки ───────────────────────────────────────────────


def test_без_выданного_кода_не_подходит_ничего():
    """Пустой код не должен совпадать с пустым вводом."""
    assert credentials.код_подходит("") is False
    assert credentials.код_подходит("ABC123") is False


def test_код_сверяется_без_учёта_регистра_и_пробелов():
    код = credentials.выдать_код_настройки()
    assert len(код) == 6
    assert credentials.код_подходит(f"  {код.lower()} ") is True
    assert credentials.код_подходит("000000") is False


# ── Хранение пароля ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_пароль_в_базе_лежит_хешем(session: AsyncSession):
    await credentials.завести(session, "owner", "igor", "длинный-пароль-владельца")

    from sqlalchemy import select

    from app.models.models import AppSetting

    строки = (await session.execute(select(AppSetting))).scalars().all()
    записано = {с.key: с.value for с in строки}

    assert "длинный-пароль-владельца" not in str(записано)
    assert записано["OWNER_PASSWORD_HASH"].startswith("pbkdf2_sha256$")
    assert записано["OWNER_LOGIN"] == "igor"


@pytest.mark.asyncio
async def test_проверка_пароля(session: AsyncSession):
    await credentials.завести(session, "owner", "igor", "длинный-пароль-владельца")

    assert credentials.проверить_пароль("owner", "igor", "длинный-пароль-владельца")
    assert not credentials.проверить_пароль("owner", "igor", "другой-пароль-тут")
    assert not credentials.проверить_пароль("owner", "не-игорь", "длинный-пароль-владельца")
    # Роль, которую не заводили, не пускает никого.
    assert not credentials.проверить_пароль("operator", "igor", "длинный-пароль-владельца")


@pytest.mark.asyncio
async def test_слабый_и_короткий_пароль_отвергаются(session: AsyncSession):
    with pytest.raises(ValueError):
        await credentials.завести(session, "owner", "igor", "короткий")
    with pytest.raises(ValueError):
        await credentials.завести(session, "owner", "", "длинный-пароль-владельца")


@pytest.mark.asyncio
async def test_смена_пароля_отменяет_старый(session: AsyncSession):
    await credentials.завести(session, "owner", "igor", "первый-пароль-владельца")
    await credentials.завести(session, "owner", "igor", "второй-пароль-владельца")

    assert not credentials.проверить_пароль("owner", "igor", "первый-пароль-владельца")
    assert credentials.проверить_пароль("owner", "igor", "второй-пароль-владельца")


@pytest.mark.asyncio
async def test_испорченная_запись_никого_не_пускает(session: AsyncSession, monkeypatch):
    """Мусор вместо хеша — это отказ, а не совпадение с чем попало."""
    await credentials.завести(session, "owner", "igor", "длинный-пароль-владельца")
    monkeypatch.setitem(credentials._учётные, "OWNER_PASSWORD_HASH", "мусор")
    assert not credentials.проверить_пароль("owner", "igor", "длинный-пароль-владельца")


# ── Вход: оба источника ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_вход_по_заведённой_записи(session: AsyncSession, пустой_env):
    from app.main import _resolve_identity
    from app.main_roles import ROLE_OPERATOR, ROLE_OWNER

    await credentials.завести(session, "owner", "igor", "длинный-пароль-владельца")
    await credentials.завести(session, "operator", "admin", "длинный-пароль-админа")

    assert _resolve_identity("igor", "длинный-пароль-владельца") == (ROLE_OWNER, None)
    assert _resolve_identity("admin", "длинный-пароль-админа") == (ROLE_OPERATOR, None)
    assert _resolve_identity("igor", "не тот пароль") is None


def test_вход_из_env_продолжает_работать():
    """У развёрнутых установок логины лежат в .env — они не должны отвалиться."""
    from app.config import settings
    from app.main import _resolve_identity
    from app.main_roles import ROLE_OWNER

    assert _resolve_identity(settings.owner_login, settings.owner_password) == (
        ROLE_OWNER,
        None,
    )
