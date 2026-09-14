"""Finance routes — marginability, break-even, plan targets."""

from datetime import date as dt_date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.schemas import CostSettingsRequest, PlanTargetRequest, PlanTargetResponse
from app.services.finance import (
    get_cost_settings,
    get_current_month_plan,
    get_daily_finance,
    get_hourly_finance,
    get_monthly_finance,
    get_plan_fact,
    set_cost_settings,
    set_monthly_plan,
)

router = APIRouter(prefix="/api/finance", tags=["finance"])


@router.get("/hourly")
async def hourly(
    date: str = Query(..., description="YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    target = dt_date.fromisoformat(date)
    return await get_hourly_finance(db, target)


@router.get("/daily")
async def daily(
    date_from: str = Query(..., description="YYYY-MM-DD"),
    date_to: str = Query(..., description="YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    d_from = dt_date.fromisoformat(date_from)
    d_to = dt_date.fromisoformat(date_to)
    return await get_daily_finance(db, d_from, d_to)


@router.get("/monthly")
async def monthly(
    year: int = Query(2026, description="Год"),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    return await get_monthly_finance(db, year)


@router.get("/costs")
async def costs(db: AsyncSession = Depends(get_db)) -> dict:
    """Структура расходов: аренда, оклады, проценты."""
    return await get_cost_settings(db)


@router.post("/costs")
async def save_costs(
    request: CostSettingsRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await set_cost_settings(db, request.model_dump())


@router.get("/plan-fact")
async def plan_fact(
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Сводка текущего месяца: факт, план и таблица по составу смены."""
    return await get_plan_fact(db)


@router.get("/plan")
async def get_plan(
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await get_current_month_plan(db)


@router.post("/plan", response_model=PlanTargetResponse)
async def set_plan(
    request: PlanTargetRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await set_monthly_plan(
        db,
        request.period,
        request.profit_target,
        request.margin_target_pct,
    )
    return result
