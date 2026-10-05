"""Страница «Финансы» — только владельцу (второй замок поверх префиксов в main.py)."""

from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.parse import unquote

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.main_roles import ROLE_OWNER
from app.services import acquiring, cash_balances, finance_analysis, owner_overview
from app.services.monthly_report import parse_month

router = APIRouter(prefix="/api/finance-analysis", tags=["finance-analysis"])

MAX_UPLOAD = 10 * 1024 * 1024


def _owner(request: Request) -> None:
    if getattr(request.state, "role", None) != ROLE_OWNER:
        raise HTTPException(403, "Недостаточно прав для этого раздела")


def _top(request: Request) -> None:
    """«Контроль финансов» (сверка с банком, отчёт эквайринга) — только Владельцу."""
    if not getattr(request.state, "top", False):
        raise HTTPException(403, "Контроль финансов доступен только Владельцу")


@router.get("")
async def report(
    request: Request, month: str | None = Query(None), db: AsyncSession = Depends(get_db)
) -> dict:
    _owner(request)
    try:
        parse_month(month or "")
    except ValueError as exc:
        raise HTTPException(422, "Выберите месяц (ГГГГ-ММ)") from exc
    try:
        данные = await finance_analysis.build(db, month)
        if not getattr(request.state, "top", False):
            # Сверка с банком по дням и поступления — «Контроль финансов».
            данные["days"] = []
            данные["totals"] = None
        return данные
    except Exception as exc:
        raise HTTPException(502, "Не удалось построить страницу: проверьте связь с YCLIENTS.") from exc


@router.get("/overview")
async def overview(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    """Страница Владельца: доход, расходы, прибыль за месяц и история за полгода."""
    _top(request)
    try:
        return await owner_overview.построить(db)
    except Exception as exc:
        raise HTTPException(502, "Не удалось построить страницу: проверьте связь с YCLIENTS.") from exc


@router.post("/acquiring")
async def upload_acquiring(
    request: Request, day: str | None = Query(None), db: AsyncSession = Depends(get_db)
) -> dict:
    """Файл отчёта банка пересылается телом запроса, имя — в заголовке X-Filename."""
    _top(request)
    name = unquote(request.headers.get("x-filename", "")) or "report"
    content = await request.body()
    if not content:
        raise HTTPException(400, "Файл пустой.")
    if len(content) > MAX_UPLOAD:
        raise HTTPException(413, "Файл больше 10 МБ.")
    try:
        день = date.fromisoformat(day) if day else None
    except ValueError as exc:
        raise HTTPException(422, "День в формате ГГГГ-ММ-ДД") from exc
    try:
        return await acquiring.сохранить(db, content, name, день)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(422, "Не удалось прочитать файл. Пришлите образец, я подстрою разбор.") from exc


@router.get("/balances")
async def balances(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    _owner(request)
    return await cash_balances.как_словарь(db) or {
        "cash_amount": None, "cash_as_of": None, "settlement_amount": None,
        "settlement_as_of": None, "other_account_debt": None, "other_debt_note": None,
        "updated_at": None,
    }


@router.post("/balances")
async def save_balances(
    request: Request, body: dict = Body(...), db: AsyncSession = Depends(get_db)
) -> dict:
    _owner(request)
    try:
        return await cash_balances.сохранить(
            db,
            cash_amount=Decimal(str(body["cash_amount"])),
            cash_as_of=date.fromisoformat(body["cash_as_of"]),
            settlement_amount=Decimal(str(body["settlement_amount"])),
            settlement_as_of=date.fromisoformat(body["settlement_as_of"]),
            other_account_debt=Decimal(str(body.get("other_account_debt") or 0)),
            other_debt_note=(body.get("other_debt_note") or None),
        )
    except (KeyError, ValueError, InvalidOperation) as exc:
        raise HTTPException(400, f"Некорректные данные: {exc}") from None
