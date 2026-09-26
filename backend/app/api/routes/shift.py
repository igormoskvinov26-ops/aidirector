"""Смена: открытие, закрытие, время мастеров и отправка в Telegram.

Кнопки ничего не шлют сами. Сначала считаются показатели, администратор их
проверяет, вносит время прихода или ухода — и только потом отдельным
действием отправляет сообщение (§3 ТЗ).
"""

from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.main_roles import ROLE_OWNER
from app.services import cash_balances, shift_store
from app.services.shift_store import ЗАКРЫТИЕ, ОТКРЫТИЕ
from app.services.telegram import TelegramNotConfiguredError, TelegramSendError

router = APIRouter(prefix="/api/shift", tags=["shift"])


def _вид(kind: str) -> str:
    if kind not in (ОТКРЫТИЕ, ЗАКРЫТИЕ):
        raise HTTPException(status_code=400, detail="kind должен быть opening или closing")
    return kind


def _require_owner(request: Request) -> None:
    if getattr(request.state, "role", None) != ROLE_OWNER:
        raise HTTPException(status_code=403, detail="Раздел доступен только владельцу")


def _день(day: str | None) -> date | None:
    if not day:
        return None
    try:
        return date.fromisoformat(day)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Дата должна быть в формате ГГГГ-ММ-ДД"
        ) from None


@router.get("/today")
async def сегодня(
    day: str | None = Query(None), db: AsyncSession = Depends(get_db)
) -> dict:
    """Состояние смены: открыта ли, закрыта ли, что уже ушло в Telegram."""
    return await shift_store.текущая(db, _день(day))


@router.post("/open")
async def открыть(
    day: str | None = Query(None), db: AsyncSession = Depends(get_db)
) -> dict:
    return await shift_store.открыть(db, _день(day))


@router.post("/close")
async def закрыть(
    day: str | None = Query(None), db: AsyncSession = Depends(get_db)
) -> dict:
    return await shift_store.закрыть(db, _день(day))


@router.post("/times")
async def времена(
    kind: str = Query(...),
    day: str | None = Query(None),
    values: dict[str, str] = Body(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Приход (kind=opening) или уход (kind=closing) мастеров: {staff_id: "09:54"}."""
    try:
        разобранные = {int(ident): время for ident, время in values.items()}
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Ключ должен быть номером мастера") from None
    try:
        return await shift_store.записать_времена(db, _вид(kind), разобранные, _день(day))
    except ValueError as сбой:
        raise HTTPException(status_code=400, detail=str(сбой)) from None


@router.get("/money/balances")
async def остатки_денег(db: AsyncSession = Depends(get_db)) -> dict:
    """Остаток в кассе, на счёте и долг по другому счёту — на дату, когда их
    в последний раз внёс владелец. None везде, если ещё ни разу не вносил."""
    сохранённые = await cash_balances.как_словарь(db)
    return сохранённые or {
        "cash_amount": None, "cash_as_of": None,
        "settlement_amount": None, "settlement_as_of": None,
        "other_account_debt": None, "other_debt_note": None, "updated_at": None,
    }


@router.post("/money/balances")
async def сохранить_остатки(
    request: Request,
    body: dict = Body(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Владелец вносит остатки заново. Значения ручные — раздел ему одному."""
    _require_owner(request)
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
    except (KeyError, ValueError, InvalidOperation) as сбой:
        raise HTTPException(status_code=400, detail=f"Некорректные данные: {сбой}") from None


@router.get("/money/{раздел}")
async def деньги(
    раздел: str,
    day: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Расшифровка плитки «Услуги» (services) или «Товары» (products)."""
    try:
        return await shift_store.деньги_детали(db, раздел, _день(day))
    except ValueError as сбой:
        raise HTTPException(status_code=400, detail=str(сбой)) from None


@router.get("/preview")
async def предпросмотр(
    kind: str = Query(...),
    day: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        return await shift_store.предпросмотр(db, _вид(kind), _день(day))
    except ValueError as сбой:
        raise HTTPException(status_code=400, detail=str(сбой)) from None


@router.post("/send")
async def отправить(
    kind: str = Query(...),
    day: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        return await shift_store.отправить(db, _вид(kind), _день(day))
    except ValueError as сбой:
        raise HTTPException(status_code=400, detail=str(сбой)) from None
    except TelegramNotConfiguredError as сбой:
        raise HTTPException(status_code=503, detail=str(сбой)) from None
    except TelegramSendError as сбой:
        raise HTTPException(status_code=502, detail=str(сбой)) from None
