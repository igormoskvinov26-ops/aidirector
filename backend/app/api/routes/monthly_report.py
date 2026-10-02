"""Месячный отчёт — только для владельца.

Оператор и мастер сюда не попадают уже на уровне префиксов в main.py; проверка
роли здесь — второй замок на случай, если префиксы когда-нибудь поменяют.
"""

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.main_roles import ROLE_OWNER
from app.services import monthly_report as mr

router = APIRouter(prefix="/api/monthly-report", tags=["monthly-report"])


def _owner(request: Request) -> None:
    if getattr(request.state, "role", None) != ROLE_OWNER:
        raise HTTPException(403, "Недостаточно прав для этого раздела")


def _month(value: str | None) -> str:
    if not value:
        raise HTTPException(422, "Выберите месяц (ГГГГ-ММ)")
    try:
        mr.parse_month(value)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return value


@router.get("")
async def report(
    request: Request,
    month: str | None = Query(None),
    refresh: bool = Query(False),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _owner(request)
    ym = _month(month)
    try:
        return await mr.build_report(db, ym, refresh=refresh)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            502, "Не удалось получить данные YCLIENTS. Отчёт не построен, повторите обновление."
        ) from exc


@router.post("/recalculate")
async def recalculate(
    request: Request, month: str | None = Query(None), db: AsyncSession = Depends(get_db)
) -> dict:
    """Контролируемый пересчёт: заново проверить звонки и пересохранить итог."""
    _owner(request)
    ym = _month(month)
    try:
        await mr.verify_pending(db, recheck_not_confirmed=True)
        return await mr.build_report(db, ym, refresh=True)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, "Не удалось получить данные YCLIENTS.") from exc


@router.get("/drilldown")
async def drilldown(
    request: Request,
    month: str | None = Query(None),
    kind: str = Query(...),
    key: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _owner(request)
    try:
        return await mr.drilldown(db, _month(month), kind, key)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, "Не удалось получить данные YCLIENTS.") from exc


@router.post("/verify")
async def verify(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    _owner(request)
    return await mr.verify_pending(db)


@router.get("/settings")
async def get_settings(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    _owner(request)
    return await mr.load_settings(db)


@router.post("/settings")
async def save_settings(
    request: Request, body: dict = Body(...), db: AsyncSession = Depends(get_db)
) -> dict:
    _owner(request)
    try:
        return await mr.save_settings(db, body)
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(422, f"Настройки не сохранены: {exc}") from exc


@router.get("/fields-probe")
async def fields_probe(request: Request) -> dict:
    _owner(request)
    try:
        return await mr.probe_fields()
    except Exception as exc:
        raise HTTPException(502, "Не удалось прочитать записи YCLIENTS.") from exc


@router.get("/today-authors")
async def today_authors(request: Request) -> dict:
    _owner(request)
    try:
        return await mr.today_authors()
    except Exception as exc:
        raise HTTPException(502, "Не удалось прочитать записи YCLIENTS.") from exc


@router.get("/staff")
async def staff(request: Request) -> dict:
    """Сотрудники и услуги YCLIENTS для выбора администраторов и допуслуг."""
    _owner(request)
    from app.api.yclients import YClientsClient

    try:
        async with YClientsClient() as client:
            staff_rows = await client.get_active_staff()
            services = await client.get_services()
    except Exception as exc:
        raise HTTPException(502, "Не удалось прочитать справочники YCLIENTS.") from exc
    return {
        "staff": [{"id": s.get("id"), "name": s.get("name")} for s in staff_rows
                  if isinstance(s, dict)],
        "services": [{"id": s.get("id"), "title": s.get("title"),
                      "category": s.get("category_id")} for s in services if isinstance(s, dict)],
    }
