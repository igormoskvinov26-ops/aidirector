"""Настройки заведения: название, барберы и ставки. Лежат в report_settings,
поэтому сами синхронизируются через общий сервер и попадают в файл настроек.

Барберы: список [{staff_id, name, service_rate, product_rate, guarantee}].
Пока владелец ничего не сохранил: для РублЪ (компания 19164) и для пустого
company_id работают прежние значения из config.py, для любой другой компании
список пуст (чужих мастеров с чужими ставками показывать нельзя).
"""

from datetime import UTC, datetime, timedelta

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services import configuration
from app.models.models import Employee, ReportSetting, Visit

RUBL_COMPANY = 19164
DEFAULT_NAME = "РублЪ"
_RUBL_RULES = list(settings.barber_payroll_rules)
name = DEFAULT_NAME
главная = True  # активен главный филиал: только у него есть прежние значения РублЪ
главное_имя = DEFAULT_NAME  # название главного филиала, пока активен другой
_RUBL_BOOKING = "n2387007.yclients.com"
booking_url = _RUBL_BOOKING


def служебный(name: str | None) -> bool:
    """«Лист ожидания» — не человек, а заглушка YCLIENTS; в расчёте мастеров ему не место.
    Сравнение по смыслу: регистр, пробелы и окончания в YCLIENTS бывают любыми."""
    return " ".join((name or "").casefold().split()).startswith("лист ожидан")


def _проверить_барберов(raw) -> list[dict]:
    out, seen = [], set()
    for b in raw or []:
        sid = int(b["staff_id"])
        if sid in seen:
            continue
        seen.add(sid)
        imya = str(b.get("name") or "").strip()
        sr, pr, g = float(b["service_rate"]), float(b["product_rate"]), float(b.get("guarantee") or 0)
        if not imya or not (0 <= sr <= 1 and 0 <= pr <= 1) or g < 0:
            raise ValueError(f"Проверьте данные мастера {imya or sid}: ставки 0–100 %, гарантия не меньше 0")
        out.append({"staff_id": sid, "name": imya, "service_rate": sr, "product_rate": pr, "guarantee": g})
    return out


def _рублъ() -> bool:
    return главная and configuration.число("YCLIENTS_COMPANY_ID") in (0, RUBL_COMPANY)


def _применить(barbers, salon_name, booking) -> None:
    global name, booking_url
    if barbers is None:
        barbers = _RUBL_RULES if _рублъ() else []
    settings.barber_payroll_rules = [b for b in barbers if not служебный(b.get("name"))]
    name = (salon_name or "").strip() or DEFAULT_NAME
    if booking is None:
        booking = _RUBL_BOOKING if _рублъ() else ""
    booking_url = str(booking).strip()


async def загрузить(session: AsyncSession) -> None:
    b = await session.get(ReportSetting, "barbers")
    n = await session.get(ReportSetting, "salon_name")
    u = await session.get(ReportSetting, "booking_url")
    _применить(b.value if b else None, n.value if n else None, u.value if u else None)


async def сохранить(session: AsyncSession, barbers=None, salon_name=None, booking=None) -> None:
    if barbers is not None:
        barbers = _проверить_барберов(barbers)
        # Убранный вручную барбер не должен вернуться при следующем автоопределении.
        before = {int(b["staff_id"]) for b in settings.barber_payroll_rules}
        now_ids = {b["staff_id"] for b in barbers}
        row = await session.get(ReportSetting, "barbers_excluded")
        excluded = ((set(row.value) if row and row.value else set()) | (before - now_ids)) - now_ids
        _записать(session, row, "barbers_excluded", sorted(excluded))
        _записать(session, await session.get(ReportSetting, "barbers"), "barbers", barbers)
    if salon_name is not None:
        s = str(salon_name).strip()[:60]
        if not s:
            raise ValueError("Название не может быть пустым")
        _записать(session, await session.get(ReportSetting, "salon_name"), "salon_name", s)
    if booking is not None:
        b = str(booking).strip().removeprefix("https://").removeprefix("http://")[:120]
        _записать(session, await session.get(ReportSetting, "booking_url"), "booking_url", b)
    await session.commit()
    await загрузить(session)


def _записать(session, row, key, value) -> None:
    if row is None:
        session.add(ReportSetting(key=key, value=value))
    else:
        row.value = value


def обзор() -> dict:
    return {"name": name, "barbers": settings.barber_payroll_rules, "booking_url": booking_url}


BARBER_WINDOW_DAYS = 60


async def определить_барберов(session: AsyncSession) -> int:
    """Барберы находятся сами: сотрудники YCLIENTS, у которых за последние
    60 дней были визиты клиентов. Администраторы и «Лист ожидания» клиентов не
    ведут, поэтому не попадают. Уже настроенные (со ставками) не удаляются:
    мастер в отпуске остаётся. Новому ставятся ставки первого из имеющихся."""
    since = datetime.now(UTC) - timedelta(days=BARBER_WINDOW_DAYS)
    rows = (await session.execute(
        select(Employee.yclients_id, Employee.name)
        .join(Visit, Visit.employee_id == Employee.id)
        .where(Visit.datetime >= since, Visit.status == "completed")
        .group_by(Employee.yclients_id, Employee.name)
    )).all()
    ex = await session.get(ReportSetting, "barbers_excluded")
    excluded = set(ex.value) if ex and ex.value else set()
    current = list(settings.barber_payroll_rules)
    have = {int(b["staff_id"]) for b in current}
    base = current[0] if current else {"service_rate": 0.4, "product_rate": 0.1, "guarantee": 0}
    added = [
        {"staff_id": int(sid), "name": name, "service_rate": base["service_rate"],
         "product_rate": base["product_rate"], "guarantee": base["guarantee"] if _рублъ() else 0}
        for sid, name in rows
        if int(sid) not in have and int(sid) not in excluded and not служебный(name)
    ]
    saved = await session.get(ReportSetting, "barbers")
    dirty = bool(saved and saved.value and any(служебный(b.get("name")) for b in saved.value))
    if not added and not dirty:
        return 0
    await сохранить_авто(session, [b for b in current + added if not служебный(b.get("name"))])
    logger.info(f"барберы определены автоматически: добавлено {len(added)}")
    return len(added)


async def сохранить_авто(session: AsyncSession, barbers: list[dict]) -> None:
    _записать(session, await session.get(ReportSetting, "barbers"), "barbers", barbers)
    await session.commit()
    await загрузить(session)
