"""Free-slot calculation — single source of truth.

This replaces four byte-identical copies of the same loop that lived inline in
main.py, and fixes the inverted logic in the original:

    working_ids = {r["staff_id"] for r in today_records}

That treated "has at least one booking today" as "is working today", so a master
with a completely empty day was reported as not working and never appeared in the
stories feed. The one person you most need to advertise was the one guaranteed to
be hidden. Working masters now come from the YCLIENTS schedule, with a documented
fallback when that endpoint is unavailable.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from loguru import logger

from app.api.yclients import YClientsClient
from app.config import settings

WAITING_LIST = "Лист Ожидания"


@dataclass
class MasterSlots:
    id: int
    name: str
    avatar: str | None
    specialization: str | None
    free_slots: list[str] = field(default_factory=list)
    booked_count: int = 0
    source: str = "schedule"

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "avatar": self.avatar,
            "specialization": self.specialization,
            "free_slots": self.free_slots,
            "booked_count": self.booked_count,
            "source": self.source,
        }


def _grid(day: date, now: datetime | None = None) -> list[str]:
    """Every bookable time on ``day``, excluding times already in the past."""
    now = now or datetime.now()
    step = timedelta(minutes=settings.slot_step_minutes)
    cursor = datetime(day.year, day.month, day.day, settings.work_open_hour, 0)
    end = datetime(day.year, day.month, day.day, 0, 0) + timedelta(
        hours=settings.work_close_hour
    )

    times: list[str] = []
    while cursor < end:
        if day > now.date() or cursor > now:
            times.append(cursor.strftime("%H:%M"))
        cursor += step
    return times


def _booked_times(records: list[dict], staff_id: int) -> set[str]:
    """Times occupied by a master, expanded across each booking's real duration.

    The original only blocked the exact start time, so a 60-minute haircut left the
    following half-hour advertised as free.
    """
    step = settings.slot_step_minutes
    busy: set[str] = set()

    for r in records:
        if r.get("staff_id") != staff_id:
            continue
        dt_raw = r.get("datetime") or ""
        if len(dt_raw) < 16:
            continue
        try:
            start = datetime.strptime(dt_raw[:16], "%Y-%m-%dT%H:%M")
        except ValueError:
            try:
                start = datetime.strptime(dt_raw[:16], "%Y-%m-%d %H:%M")
            except ValueError:
                continue

        seconds = r.get("seance_length") or 0
        minutes = int(seconds // 60) if seconds else 0
        if not minutes:
            minutes = sum(
                int(s.get("seance_length", 0) or 0) // 60 for s in r.get("services", [])
            )
        minutes = max(minutes, step)

        blocks = -(-minutes // step)  # ceil division
        for i in range(blocks):
            busy.add((start + timedelta(minutes=i * step)).strftime("%H:%M"))

    return busy


async def compute_free_slots(
    client: YClientsClient,
    day: date | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Free slots per working master for ``day`` (default: today)."""
    day = day or date.today()
    now = now or datetime.now()

    staff = await client.get_active_staff()
    records = await client.get_records_for_day(day)

    scheduled = await client.get_working_staff_ids(day)
    source = "schedule"

    if scheduled is None:
        # Fallback: schedule endpoint unreachable. Assume every active master is
        # available rather than hiding the empty ones — the failure mode of the old
        # code. Flagged in the response so the UI can say the data is approximate.
        scheduled = {s["id"] for s in staff}
        source = "fallback_all_active"
        logger.warning("schedule unavailable, assuming all active staff are working")
    elif not scheduled:
        # Genuinely nobody scheduled (day off). Still surface masters with bookings,
        # since a booking proves someone is in the chair.
        scheduled = {r.get("staff_id") for r in records if r.get("staff_id")}
        source = "derived_from_bookings"

    grid = _grid(day, now)
    masters: list[MasterSlots] = []

    for s in staff:
        sid = s["id"]
        if sid not in scheduled:
            continue
        if s.get("name") == WAITING_LIST:
            continue

        busy = _booked_times(records, sid)
        free = [t for t in grid if t not in busy]

        masters.append(
            MasterSlots(
                id=sid,
                name=s.get("name", ""),
                avatar=s.get("avatar_big") or s.get("avatar"),
                specialization=s.get("specialization"),
                free_slots=free,
                booked_count=len(busy),
                source=source,
            )
        )

    # Emptiest day first: those are the masters worth advertising.
    masters.sort(key=lambda m: (-len(m.free_slots), m.name))

    return {
        "date": day.isoformat(),
        "source": source,
        "masters": [m.as_dict() for m in masters],
        "total_free": sum(len(m.free_slots) for m in masters),
        "masters_working": len(masters),
    }


async def free_slots_for_master(
    client: YClientsClient,
    master_name: str,
    day: date | None = None,
    now: datetime | None = None,
) -> MasterSlots | None:
    """Slots for one master by name, or ``None`` if not found/not working."""
    result = await compute_free_slots(client, day=day, now=now)
    for m in result["masters"]:
        if m["name"] == master_name:
            return MasterSlots(**m)
    return None
