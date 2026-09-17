"""Sync routes — trigger data synchronization."""

from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.schemas import SyncStatusResponse
from app.services.kpi import calculate_all_daily
from app.services.sync import get_sync_state, sync_all

router = APIRouter(prefix="/api/sync", tags=["sync"])


@router.get("/status", response_model=SyncStatusResponse)
async def sync_status(db: AsyncSession = Depends(get_db)) -> SyncStatusResponse:
    """Открыт всем ролям: надпись о свежести данных стоит на каждой странице.

    Секретов здесь нет — время, шаг и количества строк. Запуск выгрузки
    (/api/sync/trigger) роли, кроме владельца, по-прежнему не получают.
    """
    return SyncStatusResponse(**await get_sync_state(db))


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
