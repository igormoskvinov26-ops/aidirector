"""Client base routes — segmentation, dashboard, admin contact queue."""


from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services import client_base
from app.services.client_base import moscow_today

router = APIRouter(prefix="/api/client-base", tags=["client-base"])


@router.get("/dashboard")
async def dashboard(
    period: str = Query("month", description="day|week|month|quarter|year"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await client_base.build_dashboard(db, period)


@router.get("/snapshots")
async def snapshots(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    return await client_base.get_snapshots(db, days)


@router.get("/timeseries")
async def timeseries(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    return await client_base.backfill_timeseries(db, days)


@router.get("/clients")
async def clients_by_segment(
    segment: str = Query(..., description="active|due|risk|late|lost"),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    return await client_base.get_clients_by_segment(db, segment)


@router.get("/segments")
async def segments(db: AsyncSession = Depends(get_db)) -> dict:
    profiles = await client_base.build_client_profiles(db)
    result = {}
    for cid, p in profiles.items():
        result[cid] = p
    return {"clients": result}


@router.post("/sync")
async def sync(db: AsyncSession = Depends(get_db)) -> dict:
    snapshot = await client_base.write_snapshot(db)
    tasks = await client_base.refresh_tasks(db)
    return {"ok": True, "snapshot": snapshot, "tasks": tasks}


@router.get("/sync/status")
async def sync_status(db: AsyncSession = Depends(get_db)) -> dict:
    snaps = await client_base.get_snapshots(db, days=1)
    last_date = snaps[-1]["date"] if snaps else None
    return {
        "last_snapshot_at": last_date,
        "is_stale": last_date != moscow_today().isoformat(),
    }


@router.get("/tasks")
async def tasks(
    status: str = Query("open"),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    return await client_base.get_tasks(db, status)


@router.post("/tasks/{task_id}/outcome")
async def task_outcome(
    task_id: int,
    body: dict = Body(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    outcome = str(body.get("outcome", ""))
    channel = str(body.get("channel", "phone"))
    comment = body.get("comment")
    actor_id = body.get("actor_id")
    return await client_base.record_outcome(db, task_id, outcome, channel, comment, actor_id)
