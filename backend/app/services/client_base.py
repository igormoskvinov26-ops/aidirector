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

from app.config import settings
from app.models.models import (
    Client,
    ContactAttempt,
    ContactTask,
    DailySegmentSnapshot,
    Employee,
    Visit,
    VisitService,
)
from app.services import call_journal
from app.services.finance import LOST_AFTER_DAYS

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


async def get_completed_visit_dates_by_master(
    session: AsyncSession,
) -> dict[int, dict[int, list[date]]]:
    """yclients_id мастера → client_id → даты завершённых визитов к нему."""
    rows = await session.execute(
        select(Employee.yclients_id, Visit.client_id, Visit.datetime)
        .join(Employee, Employee.id == Visit.employee_id)
        .where(Visit.status == "completed")
        .order_by(Employee.yclients_id, Visit.client_id, Visit.datetime)
    )
    result: dict[int, dict[int, list[date]]] = defaultdict(lambda: defaultdict(list))
    for staff_id, client_id, dt in rows:
        if dt is not None:
            result[int(staff_id)][client_id].append(_to_moscow_date(dt))
    return result


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


async def backfill_metric_history(session: AsyncSession, days: int = 90) -> dict:
    """История «Повторные»/«Потерянные» и показателей мастеров для графика
    по клику на плитку — решение владельца 18.09.2026.

    Тот же приём, что и в backfill_timeseries для сегментов: не хранит
    отдельных суточных снимков, а на каждый день окна пересчитывает нужные
    числа из дат завершённых визитов. Поэтому график заполнен на всю глубину
    истории в базе сразу, а не только с того дня, когда завели снимки.

    В отличие от живого расчёта (finance.get_return_rate,
    get_repeat_and_lost_clients), здесь не учитывается будущая запись,
    снимающая статус потерянного/нового: для прошлого дня d нельзя узнать,
    что было забронировано именно на тот момент — известно только то, что
    уже совершилось. Для сегодняшнего дня оба расчёта совпадают.

    Ключ серии — как и раньше: "global:<метрика>" на весь салон,
    "master:<staff_id>:<метрика>" на конкретного мастера.
    """
    global_dates = await get_completed_visit_dates(session)
    by_master = await get_completed_visit_dates_by_master(session)

    today = moscow_today()
    series: dict[str, list[dict]] = defaultdict(list)

    for offset in range(days, -1, -1):
        d = today - timedelta(days=offset)
        threshold = d - timedelta(days=LOST_AFTER_DAYS)

        repeat = 0
        lost = 0
        for dates in global_dates.values():
            past = [x for x in dates if x <= d]
            if not past:
                continue
            if len(past) >= 2:
                repeat += 1
            if max(past) < threshold:
                lost += 1
        series["global:repeat_clients"].append({"date": d.isoformat(), "value": repeat})
        series["global:lost_clients"].append({"date": d.isoformat(), "value": lost})

        for rule in settings.barber_payroll_rules:
            staff_id = int(rule["staff_id"])
            total = returned = new = master_lost = 0
            for dates in by_master.get(staff_id, {}).values():
                past = [x for x in dates if x <= d]
                if not past:
                    continue
                total += 1
                if len(past) >= 2:
                    returned += 1
                if min(past) >= threshold:
                    new += 1
                if max(past) < threshold:
                    master_lost += 1

            точка = {"date": d.isoformat()}
            series[f"master:{staff_id}:clients_total"].append({**точка, "value": total})
            series[f"master:{staff_id}:clients_lost"].append({**точка, "value": master_lost})
            series[f"master:{staff_id}:clients_new"].append({**точка, "value": new})
            if total > 0:
                series[f"master:{staff_id}:return_rate_pct"].append(
                    {**точка, "value": round(returned / total * 100, 1)}
                )

    return {"series": dict(series)}


# --------------------------------------------------------------------------- #
# Пульс базы: четыре сегмента в разрезе мастеров
# --------------------------------------------------------------------------- #

# Решение владельца 23.09.2026. Сегменты непересекающиеся: постоянный не
# считается заодно и лояльным, иначе столбцы в сумме дадут больше, чем есть
# клиентов, и гистограмме нельзя будет верить.
LOYAL_MIN_VISITS = 2
# Порог постоянного — пять визитов (решение владельца 23.09.2026). То же
# число действует в модуле смены: определение у постоянного клиента одно на
# всё приложение.
REGULAR_MIN_VISITS = 5

PULSE_SEGMENTS = ("new", "loyal", "regular", "lost")
PULSE_LABELS = {
    "new": "Новые",
    "loyal": "Лояльные",
    "regular": "Постоянные",
    "lost": "Потерянные",
}

# Столбец «без своего мастера»: клиент ходит в салон, но ни к одному барберу
# не набрал даже двух визитов. Ноль, а не None, — чтобы ключ ячейки был одного
# типа и в счётчиках, и в адресе запроса за списком клиентов.
NO_MASTER = 0
NO_MASTER_LABEL = "Без своего мастера"


def classify_client(
    visits_by_master: dict[int, list[date]],
    barber_ids: set[int],
    has_future_booking: bool,
    today: date,
) -> tuple[str, int] | None:
    """Сегмент клиента и столбец, в который он попадает.

    Правило приписки (решение владельца 23.09.2026): клиент идёт к тому
    мастеру, у которого был чаще; при равенстве — к тому, у кого был
    последним, это его нынешний мастер. Если ни у одного барбера не набрал
    двух визитов, а в салоне их два и больше, — попадает в столбец
    NO_MASTER: ходит в салон, но ничей. Туда же клиент, которого обслуживал
    не барбер (администратор) — своего мастера у него тоже нет.

    Один визит — исключение: такой клиент приписан к тому, кто его принял,
    даже если визит единственный. Не удержать пришедшего — это про мастера,
    и прятать такой случай в «ничьих» значило бы снять с него вопрос.

    Возвращает None для клиента без единого завершённого визита: он ещё не
    часть базы, считать его не в чем.
    """
    all_dates = [d for dates in visits_by_master.values() for d in dates]
    if not all_dates:
        return None

    у_барберов = {sid: ds for sid, ds in visits_by_master.items() if sid in barber_ids}
    if у_барберов:
        свой, визиты_к_своему = max(у_барберов.items(), key=lambda p: (len(p[1]), max(p[1])))
    else:
        свой, визиты_к_своему = NO_MASTER, []

    разрознены = len(визиты_к_своему) < LOYAL_MIN_VISITS and len(all_dates) >= LOYAL_MIN_VISITS
    столбец = NO_MASTER if разрознены else свой

    if max(all_dates) < today - timedelta(days=LOST_AFTER_DAYS) and not has_future_booking:
        return "lost", столбец
    if len(all_dates) == 1:
        return "new", столбец

    визитов = len(all_dates) if столбец == NO_MASTER else len(визиты_к_своему)
    return ("regular" if визитов >= REGULAR_MIN_VISITS else "loyal"), столбец


async def _visits_by_client_and_master(
    session: AsyncSession,
) -> dict[int, dict[int, list[date]]]:
    """client_id → yclients_id мастера → даты завершённых визитов."""
    rows = await session.execute(
        select(Visit.client_id, Employee.yclients_id, Visit.datetime)
        .join(Employee, Employee.id == Visit.employee_id)
        .where(Visit.status == "completed")
        .order_by(Visit.client_id, Visit.datetime)
    )
    result: dict[int, dict[int, list[date]]] = defaultdict(lambda: defaultdict(list))
    for client_id, staff_id, dt in rows:
        if dt is not None:
            result[client_id][int(staff_id)].append(_to_moscow_date(dt))
    return result


async def _clients_with_future_booking(session: AsyncSession) -> set[int]:
    """Кто уже записан вперёд: такого клиента потерянным звать нельзя.

    Сравнение по датам, а не по времени с часовым поясом: в тестах база
    SQLite, и арифметика с tz-aware значениями там ведёт себя иначе.
    """
    rows = await session.execute(
        select(Visit.client_id, Visit.datetime).where(Visit.status == "scheduled")
    )
    today = moscow_today()
    return {cid for cid, dt in rows if dt is not None and _to_moscow_date(dt) >= today}


def _столбцы(barbers: list[dict]) -> list[dict]:
    return [*barbers, {"staff_id": NO_MASTER, "name": NO_MASTER_LABEL}]


def _барберы() -> list[dict]:
    return [
        {"staff_id": int(rule["staff_id"]), "name": rule["name"]}
        for rule in settings.barber_payroll_rules
    ]


async def build_base_pulse(session: AsyncSession) -> dict:
    """Четыре сегмента базы в разрезе мастеров — данные для гистограмм.

    Каждый клиент попадает ровно в одну ячейку, поэтому сумма всех столбцов
    всех сегментов равна размеру базы: это и проверяется полем base_total.
    Без такого свойства по гистограмме нельзя судить, растёт база или нет.
    """
    visits = await _visits_by_client_and_master(session)
    future = await _clients_with_future_booking(session)
    today = moscow_today()
    barber_ids = {int(rule["staff_id"]) for rule in settings.barber_payroll_rules}

    counts: dict[str, dict[int, int]] = {code: defaultdict(int) for code in PULSE_SEGMENTS}
    for client_id, by_master in visits.items():
        итог = classify_client(by_master, barber_ids, client_id in future, today)
        if итог is None:
            continue
        segment, column = итог
        counts[segment][column] += 1

    столбцы = _столбцы(_барберы())
    segments = [
        {
            "code": code,
            "label": PULSE_LABELS[code],
            "total": sum(counts[code].values()),
            "columns": [
                {**столбец, "count": counts[code].get(столбец["staff_id"], 0)}
                for столбец in столбцы
            ],
        }
        for code in PULSE_SEGMENTS
    ]
    return {
        "segments": segments,
        "base_total": sum(s["total"] for s in segments),
        "lost_after_days": LOST_AFTER_DAYS,
    }


async def get_pulse_clients(session: AsyncSession, segment: str, staff_id: int) -> list[dict]:
    """Поимённо те, кто стоит за одним столбцом гистограммы.

    Потерянные отсортированы по числу визитов: вернуть постоянного клиента
    важнее, чем того, кто был однажды. Остальные — по свежести визита.
    """
    if segment not in PULSE_SEGMENTS:
        return []

    visits = await _visits_by_client_and_master(session)
    future = await _clients_with_future_booking(session)
    today = moscow_today()
    barber_ids = {int(rule["staff_id"]) for rule in settings.barber_payroll_rules}
    имена = {int(r["staff_id"]): r["name"] for r in settings.barber_payroll_rules}

    отобранные: dict[int, dict] = {}
    for client_id, by_master in visits.items():
        итог = classify_client(by_master, barber_ids, client_id in future, today)
        if итог is None or итог != (segment, staff_id):
            continue
        все_даты = [d for dates in by_master.values() for d in dates]
        последний = max(все_даты)
        свои = by_master.get(staff_id, []) if staff_id != NO_MASTER else []
        отобранные[client_id] = {
            "client_id": client_id,
            "visits_total": len(все_даты),
            "visits_to_master": len(свои),
            "master": имена.get(staff_id),
            "last_visit": последний.isoformat(),
            "days_since": (today - последний).days,
            # Дата, с которой клиент считается потерянным: последний визит
            # плюс порог. Для прочих сегментов её нет — терять нечего.
            "lost_since": (
                (последний + timedelta(days=LOST_AFTER_DAYS)).isoformat()
                if segment == "lost"
                else None
            ),
        }

    if not отобранные:
        return []

    строки = await session.execute(select(Client).where(Client.id.in_(отобранные)))
    for client in строки.scalars().all():
        отобранные[client.id].update(name=client.name, phone=client.phone)

    порядок = (
        (lambda c: (-c["visits_total"], c["days_since"]))
        if segment == "lost"
        else (lambda c: c["days_since"])
    )
    return sorted(отобранные.values(), key=порядок)


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
            "admin_note": client.admin_note,
        })
    return out


async def set_admin_note(session: AsyncSession, client_id: int, note: str) -> dict:
    """Сохранить заметку администратора на клиенте.

    Не на задаче обзвона: задачи пересобираются каждый день заново
    (refresh_tasks), а заметка должна пережить эту пересборку и снова
    появиться на карточке того же клиента.
    """
    client = await session.get(Client, client_id)
    if client is None:
        return {"ok": False, "error": "client not found"}
    client.admin_note = note.strip() or None
    await session.commit()
    return {"ok": True, "client_id": client_id, "admin_note": client.admin_note}


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
    attempt = ContactAttempt(
        task_id=task_id,
        outcome=outcome,
        channel=channel,
        comment=comment,
        actor_id=actor_id,
    )
    session.add(attempt)
    when = datetime.now(MOSCOW)
    await session.commit()

    # Результат уже сохранён. Журнал пишем после коммита и отдельно: файл на
    # диске — вещь ненадёжная, а звонок терять нельзя.
    await call_journal.append_attempt(session, task_id, attempt, when=when)
    return {"ok": True, "task_id": task_id}
