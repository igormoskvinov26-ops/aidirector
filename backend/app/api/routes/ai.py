"""AI Report routes — DeepSeek-powered management insights."""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.schemas import AIReportRequest, AIReportResponse
from app.services.ai import generate_report
from app.services.kpi import get_dashboard_data

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.post("/report", response_model=AIReportResponse)
async def ai_report(
    request: AIReportRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    date_from = date.fromisoformat(request.period_from)
    date_to = date.fromisoformat(request.period_to)

    dashboard = await get_dashboard_data(db, date_from, date_to)
    result = await generate_report(dashboard)

    return AIReportResponse(
        report=result.get("report", ""),
        insights=result.get("insights", []),
        risks=result.get("risks", []),
        opportunities=result.get("opportunities", []),
        actions_tomorrow=result.get("actions_tomorrow", []),
    )


@router.get("/quick")
async def ai_quick_report(
    db: AsyncSession = Depends(get_db),
    days: int = Query(30, description="Days to analyze"),
) -> dict:
    date_to = date.today()
    date_from = date_to - timedelta(days=days)
    dashboard = await get_dashboard_data(db, date_from, date_to)
    result = await generate_report(dashboard)
    return result
