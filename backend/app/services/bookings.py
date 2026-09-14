"""Предстоящие записи — кто придёт, когда и на какую сумму."""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.models import Client, Employee, Visit

# Записи дальше этого горизонта смотреть незачем: планирование идёт неделями,
# а список на полгода вперёд только мешает увидеть завтрашний день.
MAX_DAYS_AHEAD = 60


async def get_upcoming_bookings(
    session: AsyncSession,
    days: int = 14,
    now: datetime | None = None,
) -> dict:
    """Записи от текущего момента вперёд, сгруппированные по дням.

    Берутся только записи со статусом «запланирована»: отменённые и неявки
    сюда не попадают, иначе список бы наполнялся визитами, которых не будет.
    """
    if days < 1 or days > MAX_DAYS_AHEAD:
        raise ValueError(f"Горизонт должен быть от 1 до {MAX_DAYS_AHEAD} дней, получено {days}")

    now = now or datetime.now()
    until = now.date() + timedelta(days=days - 1)

    rows = await session.execute(
        select(Visit, Client, Employee)
        .join(Client, Visit.client_id == Client.id)
        .join(Employee, Visit.employee_id == Employee.id)
        .options(selectinload(Visit.services))
        .where(
            Visit.status == "scheduled",
            Visit.datetime >= now,
            Visit.datetime < datetime.combine(until + timedelta(days=1), datetime.min.time()),
        )
        .order_by(Visit.datetime)
    )

    by_day: dict[str, dict] = {}
    total_amount = 0.0
    total_count = 0

    for visit, client, employee in rows:
        day = visit.datetime.date().isoformat()
        bucket = by_day.setdefault(day, {
            "date": day,
            "count": 0,
            "amount": 0.0,
            "masters": set(),
            "records": [],
        })

        amount = float(visit.total_amount or 0)
        bucket["count"] += 1
        bucket["amount"] += amount
        bucket["masters"].add(employee.name)
        bucket["records"].append({
            "id": visit.id,
            "time": visit.datetime.strftime("%H:%M"),
            "client": client.name or "Без имени",
            "phone": client.phone or "",
            "is_new_client": bool(visit.is_new_client),
            "total_visits": client.total_visits,
            "master": employee.name,
            "services": [s.title for s in visit.services],
            "amount": amount,
            "comment": visit.comment or "",
        })
        total_amount += amount
        total_count += 1

    days_list = []
    for day in sorted(by_day):
        bucket = by_day[day]
        bucket["masters"] = sorted(bucket["masters"])
        bucket["amount"] = round(bucket["amount"], 2)
        days_list.append(bucket)

    return {
        "from": now.date().isoformat(),
        "to": until.isoformat(),
        "days_ahead": days,
        "total_count": total_count,
        "total_amount": round(total_amount, 2),
        "days": days_list,
    }


async def get_upcoming_summary(session: AsyncSession, now: datetime | None = None) -> dict:
    """Короткая сводка: сегодня, завтра, неделя вперёд."""
    now = now or datetime.now()
    week = await get_upcoming_bookings(session, days=7, now=now)

    today = now.date().isoformat()
    tomorrow = (now.date() + timedelta(days=1)).isoformat()

    def _for(day: str) -> dict:
        found = next((d for d in week["days"] if d["date"] == day), None)
        return {
            "count": found["count"] if found else 0,
            "amount": found["amount"] if found else 0.0,
        }

    return {
        "today": _for(today),
        "tomorrow": _for(tomorrow),
        "week": {"count": week["total_count"], "amount": week["total_amount"]},
    }
