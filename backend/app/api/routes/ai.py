"""Управленческий отчёт. Считается по правилам, без обращения наружу.

Прежняя строка говорила «DeepSeek-powered» — это осталось от версии, которая
ходила во внешний сервис. Расчёт давно ведётся в app/services/ai.py по
нормативам, ключа DeepSeek нигде в коде нет. Строку исправляю, чтобы никто не
искал ключ, которого не существует, и не считал, что Директор отправляет
данные барбершопа наружу.
"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.schemas import AIReportRequest, AIReportResponse
from app.services.ai import generate_report
from app.services.kpi import get_dashboard_data

router = APIRouter(prefix="/api/ai", tags=["ai"])

MAX_DAYS_RANGE = 365


@router.post("/report", response_model=AIReportResponse)
async def ai_report(
    request: AIReportRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    date_from = date.fromisoformat(request.period_from)
    date_to = date.fromisoformat(request.period_to)

    if (date_to - date_from).days > MAX_DAYS_RANGE:
        raise HTTPException(
            status_code=400,
            detail=f"Диапазон дат не может превышать {MAX_DAYS_RANGE} дней",
        )

    dashboard = await get_dashboard_data(db, date_from, date_to)
    result = generate_report(dashboard)

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
    days: int = Query(30, ge=1, le=MAX_DAYS_RANGE, description="Days to analyze"),
) -> dict:
    date_to = date.today()
    date_from = date_to - timedelta(days=days)
    dashboard = await get_dashboard_data(db, date_from, date_to)
    result = generate_report(dashboard)
    return result
