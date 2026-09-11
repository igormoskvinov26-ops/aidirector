"""SQLAlchemy async engine and session factory."""

from collections.abc import AsyncGenerator

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


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
