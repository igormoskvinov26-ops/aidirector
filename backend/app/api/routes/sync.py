"""Sync routes — trigger data synchronization."""

from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.schemas import SyncStatusResponse
from app.services.sync import get_sync_status, sync_all
from app.services.kpi import calculate_all_daily

router = APIRouter(prefix="/api/sync", tags=["sync"])


@router.get("/status", response_model=SyncStatusResponse)
async def sync_status() -> dict:
    status = get_sync_status()
    return SyncStatusResponse(
        in_progress=status["in_progress"],
        last_sync=status.get("last_sync"),
        records_synced=0,
        clients_synced=0,
    )


@router.post("/trigger")
async def trigger_sync(
    background_tasks: BackgroundTasks,
    date_from: str | None = Query(None, description="Start date YYYY-MM-DD"),
    date_to: str | None = Query(None, description="End date YYYY-MM-DD"),
) -> dict:
    background_tasks.add_task(sync_all, date_from=date_from, date_to=date_to)
    return {"status": "started", "message": "Sync started in background"}


@router.post("/calculate-kpi")
async def trigger_kpi(
    background_tasks: BackgroundTasks,
    days_back: int = Query(30, description="Days to calculate"),
) -> dict:
    today = date.today()
    date_from = today.replace(day=1) if days_back <= 31 else today
    from_date = date_from if days_back > 31 else today

    background_tasks.add_task(calculate_all_daily, from_date, today)
    return {"status": "started", "message": f"KPI calculation started for last {days_back} days"}
