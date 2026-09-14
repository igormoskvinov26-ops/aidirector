"""Маршруты предстоящих записей."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.bookings import MAX_DAYS_AHEAD, get_upcoming_bookings, get_upcoming_summary

router = APIRouter(prefix="/api/bookings", tags=["bookings"])


@router.get("/upcoming")
async def upcoming(
    days: int = Query(14, ge=1, le=MAX_DAYS_AHEAD, description="Горизонт в днях"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Записи вперёд, сгруппированные по дням."""
    return await get_upcoming_bookings(db, days=days)


@router.get("/summary")
async def summary(db: AsyncSession = Depends(get_db)) -> dict:
    """Сегодня, завтра и неделя одной строкой."""
    return await get_upcoming_summary(db)
