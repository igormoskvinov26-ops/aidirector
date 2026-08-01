"""Dashboard routes — aggregated analytics."""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.kpi import get_dashboard_data

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/")
async def dashboard(
    db: AsyncSession = Depends(get_db),
    days: int = Query(30, description="Number of days to cover"),
) -> dict:
    date_to = date.today()
    date_from = date_to - timedelta(days=days)
    return await get_dashboard_data(db, date_from, date_to)


@router.get("/range")
async def dashboard_range(
    db: AsyncSession = Depends(get_db),
    date_from: str = Query(..., description="Start date YYYY-MM-DD"),
    date_to: str = Query(..., description="End date YYYY-MM-DD"),
) -> dict:
    return await get_dashboard_data(
        db,
        date.fromisoformat(date_from),
        date.fromisoformat(date_to),
    )
