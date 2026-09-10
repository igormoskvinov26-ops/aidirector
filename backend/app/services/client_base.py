"""Client base segmentation and analytics.

Segmentation is based on the client's personal visit cycle (R = D / I):
  - I — median interval between completed visits (last 3–5 intervals);
  - D — days since the last completed visit;
  - R = D / I — deviation from the personal cycle.

Clients without a stable history (fewer than 4 completed visits, fewer than
3 intervals, or a chaotic cycle) fall back to fixed day brackets.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import median
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Client, ContactAttempt, ContactTask, DailySegmentSnapshot, Visit, VisitService

MOSCOW = ZoneInfo("Europe/Moscow")

# Segment ordering and human labels (must match the frontend).
SEGMENT_ORDER = ["active", "due", "risk", "late", "lost"]
SEGMENT_LABELS = {
    "active": "Активные постоянные",
    "due": "Пора записываться",
    "risk": "Зона риска",
    "late": "Сильно задерживаются",
    "lost": "Потерянные",
}

# Tunable thresholds (per the spec §5).
R_ACTIVE = 0.90
R_DUE = 1.15
R_RISK = 1.50
R_LATE = 2.00
MAD_UNSTABLE_PCT = 0.35
MIN_STABLE_VISITS = 4
MIN_STABLE_INTERVALS = 3

FALLBACK_ACTIVE_DAYS = 30
FALLBACK_DUE_DAYS = 60
FALLBACK_RISK_DAYS = 120


def moscow_today() -> date:
    return datetime.now(MOSCOW).date()


def _to_moscow_date(dt: datetime) -> date:
    if dt.tzinfo is not None:
        return dt.astimezone(MOSCOW).date()
    return dt.date()


def compute_segment(completed_dates: list[date], today: date | None = None) -> dict | None:
    """Return segment info for a client given their completed-visit dates.

    `today` is the reference date for "days since last visit" (defaults to now).
    Returns None when there is no completed history.
    """
    dates = sorted(set(completed_dates))
    n = len(dates)
    if n == 0:
        return None

    today = today or moscow_today()
    days_since = (today - dates[-1]).days

    if n < MIN_STABLE_VISITS:
        return _fallback(days_since, n)

    intervals = [(dates[i + 1] - dates[i]).days for i in range(n - 1)]
    if len(intervals) < MIN_STABLE_INTERVALS:
        return _fallback(days_since, n)

    recent = intervals[-5:] if len(intervals) >= 5 else intervals
    interval = median(recent)
    if interval <= 0:
        return _fallback(days_since, n)

    mad = median([abs(x - interval) for x in recent])
    if mad / interval > MAD_UNSTABLE_PCT:
        return _fallback(days_since, n)

    r = days_since / interval
    segment = _segment_from_r(r)
    return {
        "segment": segment,
        "stable": True,
        "r": round(r, 2),
        "interval_days": round(interval, 2),
        "days_since": days_since,
        "visits": n,
    }


def _fallback(days_since: int, visits: int) -> dict:
    if days_since <= FALLBACK_ACTIVE_DAYS:
        segment = "active"
    elif days_since <= FALLBACK_DUE_DAYS:
        segment = "due"
    elif days_since <= FALLBACK_RISK_DAYS:
        segment = "risk"
    else:
        segment = "lost"
    return {
        "segment": segment,
        "stable": False,
        "r": None,
        "interval_days": None,
        "days_since": days_since,
        "visits": visits,
    }


def _segment_from_r(r: float) -> str:
    if r < R_ACTIVE:
        return "active"
    if r <= R_DUE:
        return "due"
    if r <= R_RISK:
        return "risk"
    if r <= R_LATE:
        return "late"
    return "lost"


async def get_completed_visit_dates(session: AsyncSession) -> dict[int, list[date]]:
    rows = await session.execute(
        select(Visit.client_id, Visit.datetime)
        .where(Visit.status == "completed")
        .order_by(Visit.client_id, Visit.datetime)
    )
    result: dict[int, list[date]] = defaultdict(list)
    for client_id, dt in rows:
        if dt is not None:
            result[client_id].append(_to_moscow_date(dt))
    return dict(result)


async def build_client_profiles(session: AsyncSession) -> dict[int, dict]:
    dates_by_client = await get_completed_visit_dates(session)
    profiles: dict[int, dict] = {}
    for client_id, dates in dates_by_client.items():
        seg = compute_segment(dates)
        if seg is None:
            continue
        profiles[client_id] = {
            **seg,
            "client_id": client_id,
            "first_visit": dates[0].isoformat(),
            "last_visit": dates[-1].isoformat(),
            "visit_dates": [d.isoformat() for d in dates],
        }
    return profiles


def _period_start(period: str, today: date) -> date:
    if period == "day":
        return today
    if period == "week":
        return today - timedelta(days=6)
    if period == "quarter":
        q = (today.month - 1) // 3
        return date(today.year, q * 3 + 1, 1)
    if period == "year":
        return date(today.year, 1, 1)
    return date(today.year, today.month, 1)  # month (default)


async def build_dashboard(session: AsyncSession, period: str = "month") -> dict:
    profiles = await build_client_profiles(session)
    today = moscow_today()
    start = _period_start(period, today)

    counts = defaultdict(int)
    new_clients = 0
    returned = 0
    became_regular = 0
    became_risk = 0
    became_lost = 0
    for p in profiles.values():
        counts[p["segment"]] += 1
        dates = [date.fromisoformat(d) for d in p["visit_dates"]]

        if dates[0] >= start:
            new_clients += 1

        # "returned": came back in the period after a long absence (>120 days gap).
        if len(dates) >= 2 and dates[-1] >= start:
            gap = (dates[-1] - dates[-2]).days
            if gap > FALLBACK_RISK_DAYS:
                returned += 1

        # "became regular": the 4th completed visit (stable-history threshold) is in the period.
        if len(dates) >= MIN_STABLE_VISITS and dates[MIN_STABLE_VISITS - 1] >= start:
            became_regular += 1

        # outflow: clients whose last visit is in the period and are now at risk / lost.
        if dates[-1] >= start:
            if p["segment"] in ("risk", "late"):
                became_risk += 1
            elif p["segment"] == "lost":
                became_lost += 1

    active_base = sum(1 for p in profiles.values() if p["segment"] != "lost")
    at_risk = counts["risk"] + counts["late"]
    inflow = new_clients + returned
    outflow = became_risk + became_lost

    segments = [
        {"code": code, "label": SEGMENT_LABELS[code], "count": counts.get(code, 0)}
        for code in SEGMENT_ORDER
    ]

    return {
        "generatedAt": datetime.now(MOSCOW).isoformat(),
        "period": period,
        "metrics": {
            "active_base": active_base,
            "new": new_clients,
            "became_regular": became_regular,
            "at_risk": at_risk,
            "lost": counts.get("lost", 0),
            "returned": returned,
            "total": len(profiles),
        },
        "flow": {
            "new": new_clients,
            "returned": returned,
            "became_risk": became_risk,
            "became_lost": became_lost,
            "inflow": inflow,
            "outflow": outflow,
            "net": inflow - outflow,
        },
        "segments": segments,
    }


async def write_snapshot(session: AsyncSession) -> dict:
    profiles = await build_client_profiles(session)
    today = moscow_today()
    counts: dict[str, int] = defaultdict(int)
    for p in profiles.values():
        counts[p["segment"]] += 1

    for code in SEGMENT_ORDER:
        await session.merge(
            DailySegmentSnapshot(
                snapshot_date=today,
                segment_code=code,
                clients_count=counts.get(code, 0),
            )
        )
    await session.commit()
    return {"snapshot_date": today.isoformat(), "segments": dict(counts)}


async def get_snapshots(session: AsyncSession, days: int = 30) -> list[dict]:
    since = moscow_today() - timedelta(days=days)
    rows = await session.execute(
        select(DailySegmentSnapshot)
        .where(DailySegmentSnapshot.snapshot_date >= since)
        .order_by(DailySegmentSnapshot.snapshot_date)
    )
    by_date: dict[str, dict[str, int]] = defaultdict(dict)
    for snap in rows.scalars().all():
        by_date[snap.snapshot_date.isoformat()][snap.segment_code] = snap.clients_count
    return [
        {"date": d, "segments": segs}
        for d, segs in sorted(by_date.items())
    ]


async def backfill_timeseries(session: AsyncSession, days: int = 30) -> list[dict]:
    """Rebuild segment counts for each of the last `days` days from visit history.

    Used for the "Пульс базы" chart — historical active base, not just today's state.
    """
    dates_by_client = await get_completed_visit_dates(session)
    today = moscow_today()
    out: list[dict] = []
    for offset in range(days, -1, -1):
        d = today - timedelta(days=offset)
        counts: dict[str, int] = defaultdict(int)
        for dates in dates_by_client.values():
            past = [x for x in dates if x <= d]
            if not past:
                continue
            seg = compute_segment(past, today=d)
            if seg:
                counts[seg["segment"]] += 1
        active = sum(v for k, v in counts.items() if k != "lost")
        row: dict = {"date": d.isoformat(), "active_base": active}
        for code in SEGMENT_ORDER:
            row[code] = counts.get(code, 0)
        out.append(row)
    return out


async def get_clients_by_segment(session: AsyncSession, segment: str) -> list[dict]:
    profiles = await build_client_profiles(session)
    ids = [cid for cid, p in profiles.items() if p["segment"] == segment]
    clients: dict[int, Client] = {}
    if ids:
        rows = await session.execute(select(Client).where(Client.id.in_(ids)))
        for c in rows.scalars().all():
            clients[c.id] = c

    out = []
    for cid in ids:
        p = profiles[cid]
        c = clients.get(cid)
        out.append({
            "client_id": cid,
            "name": c.name if c else None,
            "phone": c.phone if c else None,
            "segment": p["segment"],
            "stable": p["stable"],
            "days_since": p["days_since"],
            "r": p["r"],
            "interval_days": p["interval_days"],
            "visits": p["visits"],
            "last_visit": p["last_visit"],
        })
    out.sort(key=lambda x: -(x["days_since"] or 0))
    return out


# ---------------------------------------------------------------------------
# Admin contact queue
# ---------------------------------------------------------------------------
TASK_PRIORITY = {"lost": 5, "late": 4, "risk": 3, "due": 2}

TASK_SCRIPTS = {
    "due": {
        "goal": "Предложить удобное время для записи",
        "phone": "Здравствуйте, {name}! Подскажите, когда вам удобно записаться?",
        "message": "{name}, здравствуйте! Мы соскучились. Подобрать удобное время для стрижки?",
    },
    "risk": {
        "goal": "Персональное напоминание или звонок",
        "phone": "Здравствуйте, {name}! Вы давно у нас не были. Удобно ли записаться на этой неделе?",
        "message": "{name}, здравствуйте! Напомним о себе — будем рады видеть вас в РублЪ.",
    },
    "late": {
        "goal": "Уточнить причину паузы и получить обратную связь",
        "phone": "Здравствуйте, {name}! Давно не виделись. Всё ли было хорошо в прошлый раз?",
        "message": "{name}, здравствуйте! Если что-то было не так — расскажите, мы исправим.",
    },
    "lost": {
        "goal": "Сценарий возврата без давления",
        "phone": "Здравствуйте, {name}! Мы по вам скучаем. Будем рады видеть вас снова.",
        "message": "{name}, здравствуйте! Возвращайтесь — у нас для вас будет приятный сюрприз.",
    },
}

ACTIONABLE_SEGMENTS = ["due", "risk", "late", "lost"]


async def refresh_tasks(session: AsyncSession) -> dict:
    """Regenerate today's contact queue from actionable segments (no duplicates)."""
    profiles = await build_client_profiles(session)
    today = moscow_today()

    client_ids = [cid for cid, p in profiles.items() if p["segment"] in ACTIONABLE_SEGMENTS]
    clients = {}
    if client_ids:
        rows = await session.execute(select(Client).where(Client.id.in_(client_ids)))
        for c in rows.scalars().all():
            clients[c.id] = c

    # Remove all still-open tasks (idempotent daily refresh — old days' tasks are stale).
    from sqlalchemy import delete
    await session.execute(
        delete(ContactTask).where(ContactTask.status == "open")
    )

    created = 0
    for cid, p in profiles.items():
        if p["segment"] not in ACTIONABLE_SEGMENTS:
            continue
        client = clients.get(cid)
        task = ContactTask(
            client_id=cid,
            group_code=p["segment"],
            priority=TASK_PRIORITY.get(p["segment"], 1),
            due_date=today,
            status="open",
            script_version="v1",
        )
        session.add(task)
        created += 1

    await session.commit()
    return {"tasks_created": created, "date": today.isoformat()}


async def get_last_service_map(session: AsyncSession, client_ids: list[int]) -> dict[int, str]:
    """Map client_id → title of the primary service of their most recent completed visit."""
    if not client_ids:
        return {}
    rows = await session.execute(
        select(Visit.client_id, Visit.datetime, VisitService.title)
        .join(VisitService, VisitService.visit_id == Visit.id)
        .where(Visit.client_id.in_(client_ids), Visit.status == "completed")
        .order_by(Visit.client_id, Visit.datetime.desc(), VisitService.id)
    )
    result: dict[int, str] = {}
    for client_id, _dt, title in rows:
        if client_id not in result and title:
            result[client_id] = title
    return result


async def get_tasks(session: AsyncSession, status: str = "open") -> list[dict]:
    today = moscow_today()
    cond = ContactTask.status == status
    if status == "open":
        # the queue is for today only
        cond = cond & (ContactTask.due_date == today)
    rows = await session.execute(
        select(ContactTask, Client)
        .join(Client, Client.id == ContactTask.client_id)
        .where(cond)
        .order_by(ContactTask.due_date.desc(), ContactTask.priority.desc())
    )
    pairs = [(task, client) for task, client in rows.all()]

    client_ids = [c.id for _, c in pairs]
    dates_map = await get_completed_visit_dates(session)
    last_service_map = await get_last_service_map(session, client_ids)

    out = []
    for task, client in pairs:
        dates = dates_map.get(client.id, [])
        script = TASK_SCRIPTS.get(task.group_code, {})
        out.append({
            "id": task.id,
            "client_id": client.id,
            "client_name": client.name,
            "phone": client.phone,
            "group_code": task.group_code,
            "priority": task.priority,
            "due_date": task.due_date.isoformat(),
            "status": task.status,
            "script_version": task.script_version,
            "visits_count": len(dates),
            "last_visit": dates[-1].isoformat() if dates else None,
            "last_service": last_service_map.get(client.id),
            "goal": script.get("goal", ""),
            "phone_script": script.get("phone", "").replace("{name}", client.name or ""),
            "message_script": script.get("message", "").replace("{name}", client.name or ""),
        })
    return out


async def record_outcome(
    session: AsyncSession,
    task_id: int,
    outcome: str,
    channel: str,
    comment: str | None,
    actor_id: str | None,
) -> dict:
    task = await session.get(ContactTask, task_id)
    if task is None:
        return {"ok": False, "error": "task not found"}
    task.status = "done"
    session.add(ContactAttempt(
        task_id=task_id,
        outcome=outcome,
        channel=channel,
        comment=comment,
        actor_id=actor_id,
    ))
    await session.commit()
    return {"ok": True, "task_id": task_id}
