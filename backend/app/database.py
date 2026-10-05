"""SQLAlchemy async engine and session factory."""

from collections.abc import AsyncGenerator

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


BASE_URL = settings.database_url  # адрес главной базы; базы филиалов отличаются только именем


def _make_engine(url: str):
    return create_async_engine(
        url, echo=settings.debug, pool_size=10, max_overflow=20, pool_pre_ping=True
    )


def _make_maker(eng):
    return async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)


_state: dict = {"engine": _make_engine(BASE_URL)}
_state["maker"] = _make_maker(_state["engine"])


class _EngineProxy:
    """Движок, который можно подменить на лету: филиал = своя база."""

    def __getattr__(self, name):
        return getattr(_state["engine"], name)


class _MakerProxy:
    def __call__(self, *a, **k):
        return _state["maker"](*a, **k)


engine = _EngineProxy()
async_session = _MakerProxy()


def url_for(db_name: str) -> str:
    return BASE_URL.rsplit("/", 1)[0] + "/" + db_name


async def use_database(db_name: str) -> None:
    """Переключить приложение на базу филиала. Уже открытые сессии доживают на старой."""
    old = _state["engine"]
    new = _make_engine(url_for(db_name))
    async with new.connect() as conn:  # не переключаемся на недоступную базу
        await conn.execute(text("SELECT 1"))
    _state["engine"], _state["maker"] = new, _make_maker(new)
    await old.dispose()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


async def check_db() -> str:
    """Health-probe the database without raising."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return "ok"
    except Exception as exc:
        logger.error(f"database check failed: {exc}")
        return "unavailable"


async def init_db() -> None:
    """Verify connectivity at startup.

    Schema creation is owned by Alembic (`alembic upgrade head`), not by
    create_all — otherwise the first model change has to be applied to the live
    database by hand.
    """
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
