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

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.models import (
    AppSetting,
    Client,
    ClientTag,
    ClientTagLink,
    ContactAttempt,
    ContactTask,
    DailySegmentSnapshot,
    Employee,
    Script,
    Visit,
    VisitService,
)
from app.services import call_journal
from app.services.finance import LOST_AFTER_DAYS

MOSCOW = ZoneInfo(settings.timezone)

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


def поток_клиента(dates: list[date], start: date, today: date) -> dict[str, int]:
    """Приход и уход одного клиента внутри периода — по правилу «Пульса базы».

    До 16.10.2026 баланс движения считал отток как «клиентов, чей последний
    визит попал в период и кто сейчас в риске или потерян». Это не работало:
    тот, кто стал потерянным в октябре, последний раз приходил летом, в период
    не попадал и в отток не считался. Баланс выходил почти всегда плюсовым,
    хотя пульс базы был минусовым каждый день.

    Теперь оба считают одинаково: новый — первый визит в периоде, потерянный —
    день, когда с последнего визита прошло LOST_AFTER_DAYS, вернувшийся —
    визит после такого перерыва. Поэтому «чистый прирост» за период равен
    сумме дневных пульсов за тот же период.
    """
    v = sorted(set(dates))
    if not v:
        return {"new": 0, "returned": 0, "lost": 0}

    def в_периоде(d: date) -> bool:
        return start <= d <= today

    новый = int(в_периоде(v[0]))
    вернулись = потеряны = 0
    for a, b in zip(v, v[1:]):
        if (b - a).days > LOST_AFTER_DAYS:
            потеряны += в_периоде(a + timedelta(days=LOST_AFTER_DAYS + 1))
            вернулись += в_периоде(b)
    потеряны += в_периоде(v[-1] + timedelta(days=LOST_AFTER_DAYS + 1))
    return {"new": новый, "returned": вернулись, "lost": потеряны}


async def build_dashboard(session: AsyncSession, period: str = "month") -> dict:
    profiles = await build_client_profiles(session)
    today = moscow_today()
    start = _period_start(period, today)

    counts = defaultdict(int)
    new_clients = 0
    returned = 0
    became_regular = 0
    became_lost = 0
    for p in profiles.values():
        counts[p["segment"]] += 1
        dates = [date.fromisoformat(d) for d in p["visit_dates"]]
        поток = поток_клиента(dates, start, today)

        new_clients += поток["new"]
        returned += поток["returned"]
        became_lost += поток["lost"]

        # "became regular": the 4th completed visit (stable-history threshold) is in the period.
        if len(dates) >= MIN_STABLE_VISITS and dates[MIN_STABLE_VISITS - 1] >= start:
            became_regular += 1

    active_base = sum(1 for p in profiles.values() if p["segment"] != "lost")
    at_risk = counts["risk"] + counts["late"]
    inflow = new_clients + returned
    outflow = became_lost

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
            "became_lost": became_lost,
            # Зона риска — это состояние, а не выход из базы: клиент ещё наш.
            # В арифметику баланса она не входит, показываем отдельной строкой.
            "at_risk_now": at_risk,
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
# Пульс базы: пять сегментов, столбец — последний мастер клиента
# --------------------------------------------------------------------------- #

# Решение владельца 25.09.2026. Сегмент — по числу визитов клиента во всём
# салоне, не к одному мастеру: прежняя приписка «к своему мастеру по частоте
# визитов» с отдельным столбцом для «разрозненных» была источником путаницы
# и двойного счёта. Столбец гистограммы теперь — просто тот, кто вёл
# последний завершённый визит: одно значение на клиента, без вычислений.
#
# Сегменты непересекающиеся и покрывают всю базу без остатка: постоянный не
# считается заодно лояльным, иначе столбцы в сумме дадут больше, чем есть
# клиентов, и гистограмме нельзя будет верить.
SECOND_VISITS = 2
LOYAL_MAX_VISITS = 9

PULSE_SEGMENTS = ("new", "second", "loyal", "vip", "lost")
PULSE_LABELS = {
    "new": "Новые",
    "second": "Второй визит",
    "loyal": "Лояльные",
    "vip": "VIP",
    "lost": "Потерянные",
}

# Зона риска (решение владельца 25.09.2026): клиент ещё не потерян, но
# последний визит был давно — самое время напомнить о записи, пока он не
# перешёл в потерянные. Отдельный блок, а не сегмент: он пересекается с
# любым из пяти выше (новый или VIP — не важно, важна только свежесть
# визита), поэтому в base_total не входит.
RISK_ZONE_MIN_DAYS = 28
RISK_ZONE_CODE = "risk"
RISK_ZONE_LABEL = "Зона риска"

# Столбец «без своего мастера»: последний визит клиента вёл не барбер
# (администратор) либо мастер уже не значится в штате. Ноль, а не None, —
# чтобы ключ ячейки был одного типа и в счётчиках, и в адресе запроса за
# списком клиентов.
NO_MASTER = 0
NO_MASTER_LABEL = "Без своего мастера"


def _столбец_мастера(last_master: int | None, barber_ids: set[int]) -> int:
    """Последний мастер клиента, если это барбер, иначе NO_MASTER.

    Общая точка для сегментов «Пульса базы» и для «Зоны риска»: и там, и там
    столбец гистограммы — один и тот же последний мастер, определённый
    одинаково, чтобы клиент не оказывался в разных столбцах на соседних
    графиках.
    """
    return last_master if last_master in barber_ids else NO_MASTER


def classify_client(
    visits: list[date],
    last_master: int | None,
    barber_ids: set[int],
    has_future_booking: bool,
    today: date,
) -> tuple[str, int] | None:
    """Сегмент клиента и столбец, в который он попадает.

    Столбец — последний мастер, который вёл завершённый визит клиента.
    Если это был не барбер (администратор) или мастер не найден в штате —
    столбец NO_MASTER. Никакой приписки «по частоте» и разбора разрозненных
    визитов: одно значение, вычисленное заранее в SQL-запросе, а не здесь.

    Сегмент — по общему числу визитов, независимо от того, к какому мастеру
    они были: 1 → новый, 2 → второй визит, 3–9 → лояльный, 10 и больше →
    VIP. Свежесть последнего визита это переопределяет: 60 дней и больше без
    визита и без записи вперёд — потерянный, каким бы ни было число визитов.

    Возвращает None для клиента без единого завершённого визита: он ещё не
    часть базы, считать его не в чем.
    """
    if not visits:
        return None

    столбец = _столбец_мастера(last_master, barber_ids)

    if max(visits) < today - timedelta(days=LOST_AFTER_DAYS) and not has_future_booking:
        return "lost", столбец

    n = len(visits)
    if n == 1:
        return "new", столбец
    if n == SECOND_VISITS:
        return "second", столбец
    if n <= LOYAL_MAX_VISITS:
        return "loyal", столбец
    return "vip", столбец


def в_зоне_риска(last_visit: date, has_future_booking: bool, today: date) -> bool:
    """Клиент не потерян, но давно не был — самое время напомнить о записи.

    Порог владельца 25.09.2026: больше 28 и меньше 60 дней с последнего
    визита. Нижняя граница отделяет зону риска от тех, кто был недавно и
    напоминание ещё не нужно; верхняя — LOST_AFTER_DAYS, тот же порог, что
    и у «потерянных»: после него звонить поздно, клиент уже в другом списке.

    Запись вперёд снимает необходимость напоминать — как и для «потерянных»:
    звать в салон того, кто уже записан, незачем.
    """
    if has_future_booking:
        return False
    дней = (today - last_visit).days
    return RISK_ZONE_MIN_DAYS < дней < LOST_AFTER_DAYS


async def _client_visit_summary(
    session: AsyncSession,
) -> tuple[dict[int, list[date]], dict[int, int]]:
    """client_id → даты завершённых визитов, и client_id → мастер последнего из них.

    Одним запросом вместо группировки по мастеру: строки идут по возрастанию
    datetime внутри каждого клиента, поэтому последняя строка на клиента —
    это и есть его последний визит, а её мастер — «последний мастер» без
    дополнительных вычислений.
    """
    rows = await session.execute(
        select(Visit.client_id, Employee.yclients_id, Visit.datetime)
        .join(Employee, Employee.id == Visit.employee_id)
        .where(Visit.status == "completed")
        .order_by(Visit.client_id, Visit.datetime)
    )
    даты: dict[int, list[date]] = defaultdict(list)
    последний_мастер: dict[int, int] = {}
    for client_id, staff_id, dt in rows:
        if dt is None:
            continue
        даты[client_id].append(_to_moscow_date(dt))
        последний_мастер[client_id] = int(staff_id)  # строки идут по возрастанию datetime
    return даты, последний_мастер


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
    """Пять сегментов базы плюс зона риска, в разрезе последнего мастера.

    Каждый клиент попадает ровно в одну ячейку из пяти сегментов, поэтому
    сумма их столбцов равна размеру базы: это и проверяется полем
    base_total. Без такого свойства по гистограмме нельзя судить, растёт
    база или нет. Зона риска в этот подсчёт не входит: она пересекается с
    любым из пяти сегментов (важна только свежесть визита, а не их число).
    """
    даты, последний_мастер = await _client_visit_summary(session)
    future = await _clients_with_future_booking(session)
    today = moscow_today()
    barber_ids = {int(rule["staff_id"]) for rule in settings.barber_payroll_rules}
    столбцы = _столбцы(_барберы())

    counts: dict[str, dict[int, int]] = {code: defaultdict(int) for code in PULSE_SEGMENTS}
    risk_counts: dict[int, int] = defaultdict(int)
    for client_id, visits in даты.items():
        has_future = client_id in future
        мастер = последний_мастер.get(client_id)
        столбец = _столбец_мастера(мастер, barber_ids)

        итог = classify_client(visits, мастер, barber_ids, has_future, today)
        if итог is not None:
            segment, column = итог
            counts[segment][column] += 1

        if в_зоне_риска(max(visits), has_future, today):
            risk_counts[столбец] += 1

    segments = [
        {
            "code": code,
            "label": PULSE_LABELS[code],
            "total": sum(counts[code].values()),
            "columns": [
                {**с, "count": counts[code].get(с["staff_id"], 0)} for с in столбцы
            ],
        }
        for code in PULSE_SEGMENTS
    ]
    risk_zone = {
        "code": RISK_ZONE_CODE,
        "label": RISK_ZONE_LABEL,
        "total": sum(risk_counts.values()),
        "columns": [
            {**с, "count": risk_counts.get(с["staff_id"], 0)} for с in столбцы
        ],
    }
    return {
        "segments": segments,
        "risk_zone": risk_zone,
        "base_total": sum(s["total"] for s in segments),
        "lost_after_days": LOST_AFTER_DAYS,
        "risk_zone_min_days": RISK_ZONE_MIN_DAYS,
    }


async def get_pulse_clients(session: AsyncSession, segment: str, staff_id: int) -> list[dict]:
    """Поимённо те, кто стоит за одним столбцом гистограммы.

    Потерянные отсортированы по числу визитов: вернуть VIP важнее, чем
    того, кто был однажды. Зона риска — по свежести визита наоборот: чем
    ближе к порогу потерянных, тем срочнее звонить, такие идут первыми.
    Остальные — по свежести визита, недавние впереди.
    """
    if segment not in (*PULSE_SEGMENTS, RISK_ZONE_CODE):
        return []

    даты, последний_мастер = await _client_visit_summary(session)
    future = await _clients_with_future_booking(session)
    today = moscow_today()
    barber_ids = {int(rule["staff_id"]) for rule in settings.barber_payroll_rules}
    имена = {int(r["staff_id"]): r["name"] for r in settings.barber_payroll_rules}

    отобранные: dict[int, dict] = {}
    for client_id, visits in даты.items():
        has_future = client_id in future
        последний = max(visits)

        if segment == RISK_ZONE_CODE:
            столбец = _столбец_мастера(последний_мастер.get(client_id), barber_ids)
            if not в_зоне_риска(последний, has_future, today) or столбец != staff_id:
                continue
        else:
            итог = classify_client(
                visits, последний_мастер.get(client_id), barber_ids, has_future, today
            )
            if итог is None or итог != (segment, staff_id):
                continue

        отобранные[client_id] = {
            "client_id": client_id,
            "visits_total": len(visits),
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
        отобранные[client.id].update(name=client.name, phone=client.phone,
                                     do_not_call=bool(client.do_not_call))

    порядок = (
        (lambda c: (-c["visits_total"], c["days_since"]))
        if segment == "lost"
        else (lambda c: -c["days_since"])
        if segment == RISK_ZONE_CODE
        else (lambda c: c["days_since"])
    )
    return sorted(отобранные.values(), key=порядок)


# Плитки «Новые», «Стали постоянными», «Вернули» — это события за период, а не
# сегмент на сегодня. Клик по ним показывает список тех самых клиентов (решение
# владельца 04.10.2026: все плитки должны открываться). Правила — те же, что в
# build_dashboard, чтобы число на плитке совпадало с длиной списка.
МЕТРИКИ_ПЕРИОДА = ("new", "became_regular", "returned")


def _в_метрике(p: dict, metric: str, start: date) -> bool:
    dates = [date.fromisoformat(d) for d in p["visit_dates"]]
    if metric == "new":
        return dates[0] >= start
    if metric == "returned":
        return len(dates) >= 2 and dates[-1] >= start and (dates[-1] - dates[-2]).days > FALLBACK_RISK_DAYS
    if metric == "became_regular":
        return len(dates) >= MIN_STABLE_VISITS and dates[MIN_STABLE_VISITS - 1] >= start
    return False


async def get_clients_by_segment(session: AsyncSession, segment: str, period: str = "month") -> list[dict]:
    profiles = await build_client_profiles(session)
    if segment in МЕТРИКИ_ПЕРИОДА:
        start = _period_start(period, moscow_today())
        ids = [cid for cid, p in profiles.items() if _в_метрике(p, segment, start)]
    elif segment == "active_base":
        ids = [cid for cid, p in profiles.items() if p["segment"] != "lost"]
    else:
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
            "do_not_call": bool(c.do_not_call) if c else False,
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
TASK_PRIORITY = {"callback": 6, "lost": 5, "late": 4, "risk": 3, "due": 2}

TASK_SCRIPTS = {
    "due": {
        "goal": "Предложить удобное время для записи",
        "phone": "Здравствуйте, {name}! Подскажите, когда вам удобно записаться?",
        "message": "{name}, здравствуйте! Мы соскучились. Подобрать удобное время для стрижки?",
    },
    "risk": {
        "goal": "Персональное напоминание или звонок",
        "phone": "Здравствуйте, {name}! Вы давно у нас не были. Удобно ли записаться на этой неделе?",
        "message": "{name}, здравствуйте! Напомним о себе — будем рады видеть вас снова.",
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
    "callback": {
        "goal": "Перезвонить, как договаривались",
        "phone": "Здравствуйте, {name}! Обещал(а) вам перезвонить — подобрать время?",
        "message": "{name}, здравствуйте! Как договаривались, напоминаю о себе.",
    },
}

ACTIONABLE_SEGMENTS = ["due", "risk", "late", "lost"]

# Клиент, которого админ нашёл поиском и открыл, хотя повода звонить ему по
# сегментам нет (например, сам позвонил в салон).
ГРУППА_ПОИСК = "manual"
TASK_PRIORITY[ГРУППА_ПОИСК] = 7
# Метка в script_version: задачу открыли из поиска, пересборка её не трогает.
ИЗ_ПОИСКА = "search"


def цифры(s: str | None) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())


async def search_by_phone(session: AsyncSession, запрос: str, limit: int = 20) -> list[dict]:
    """Клиенты, в номере которых встречаются эти цифры подряд (любая часть
    номера, в том числе последние 4). Номер набирают как угодно: «8 926…»
    находит записанный «+7 926…».

    ponytail: перебор всей базы в Python — у салона несколько тысяч клиентов,
    это миллисекунды; при десятках тысяч — индекс по цифрам номера.
    """
    q = цифры(запрос)
    if len(q) < 3:
        return []
    варианты = {q}
    if len(q) >= 2 and q[0] == "8":
        варианты.add("7" + q[1:])
    rows = (await session.execute(
        select(Client.id, Client.name, Client.phone, Client.do_not_call)
    )).all()
    найдено = [r for r in rows if any(в in цифры(r.phone) for в in варианты)][:limit]
    даты = await get_completed_visit_dates(session) if найдено else {}
    return [{
        "client_id": r.id, "name": r.name, "phone": r.phone,
        "do_not_call": bool(r.do_not_call),
        "last_visit": даты[r.id][-1].isoformat() if даты.get(r.id) else None,
    } for r in найдено]


ГРУППА_ТЕРЯЕМ = "losing"
TASK_PRIORITY[ГРУППА_ТЕРЯЕМ] = 8


def теряем_сегодня(profiles: dict[int, dict], с_записью: set[int], today: date) -> set[int]:
    """Кто становится потерянным сегодня: последний визит ровно LOST_AFTER_DAYS
    дней назад и записи вперёд нет. Тот же рубеж, что в отчёте смены."""
    рубеж = (today - timedelta(days=LOST_AFTER_DAYS)).isoformat()
    return {cid for cid, p in profiles.items() if p.get("last_visit") == рубеж and cid not in с_записью}


def _группа_клиента(dates: list[date], today: date) -> str:
    сегмент = (compute_segment(dates, today) or {}).get("segment")
    return сегмент or "no_visits"


async def вся_база(session: AsyncSession) -> list[dict]:
    """Вся клиентская база одной таблицей (решение владельца 30.10.2026).

    Очередь обзвона на сегодня — не отдельный список, а признаки строки:
    ``task_id``, ``in_queue``, ``lost_today``, ``callback_due``. Имена и
    телефоны отсюда никуда, кроме экрана Пульта, не уходят.

    ponytail: вся база одним ответом — у салона несколько тысяч клиентов;
    при десятках тысяч — постраничная выдача с фильтрами на сервере.
    """
    today = moscow_today()
    клиенты = (await session.execute(select(Client))).scalars().all()
    ids = [c.id for c in клиенты]
    даты = await get_completed_visit_dates(session)
    теги = await tags_by_client(session, ids)
    мастера = await last_master_map(session, ids)
    с_записью = await _clients_with_future_booking(session)
    задачи: dict[int, ContactTask] = {}
    for t in (await session.execute(
        select(ContactTask).where(ContactTask.due_date == today).order_by(ContactTask.status.desc())
    )).scalars():
        задачи[t.client_id] = t  # open перекрывает done: сортировка status desc

    out = []
    for c in клиенты:
        d = даты.get(c.id, [])
        дней = (today - d[-1]).days if d else None
        задача = задачи.get(c.id)
        звонок = c.last_call_at
        if звонок is not None:
            звонок = звонок.astimezone(MOSCOW) if звонок.tzinfo else звонок.replace(tzinfo=MOSCOW)
        out.append({
            "client_id": c.id,
            "name": c.name,
            "phone": c.phone,
            # Ссылки в YCLIENTS здесь нет: она ~800 знаков и на 4 тыс. строк
            # раздувала ответ до 4,6 МБ — переход в базу тормозил. Шаблон
            # отдаётся один раз (шаблон_yclients), ссылку собирает экран.
            "group_code": задача.group_code if задача else _группа_клиента(d, today),
            "task_id": задача.id if задача else None,
            "in_queue": задача is not None,
            "called_today": bool(звонок and звонок.date() == today),
            "priority": задача.priority if задача else 0,
            "visits_count": len(d),
            "last_visit": d[-1].isoformat() if d else None,
            "days_since_visit": дней,
            "future_booking": c.id in с_записью,
            "lost_today": дней == LOST_AFTER_DAYS and c.id not in с_записью,
            "call_status": c.call_status,
            "last_call_at": звонок.isoformat() if звонок else None,
            "last_call_by": c.last_call_by,
            "next_contact_at": c.next_contact_at.isoformat() if c.next_contact_at else None,
            "callback_due": bool(c.next_contact_at and c.next_contact_at <= today),
            "tags": теги.get(c.id, []),
            "last_master": мастера.get(c.id),
            "loyalty": c.loyalty,
            "admin_note": c.admin_note,
            "do_not_call": bool(c.do_not_call),
        })
    # Сначала сегодняшняя очередь в её порядке, затем остальные — давно не
    # бывшие выше.
    def ключ(r: dict) -> tuple:
        if r["in_queue"]:
            обзвонён = r["called_today"]
            ступень = 3 if обзвонён else (-1 if r["lost_today"] else 0 if r["callback_due"] else 1)
            return (0, ступень, -r["priority"], r["last_call_at"] or "")
        return (1, 0, -(r["days_since_visit"] if r["days_since_visit"] is not None else -1), "")

    out.sort(key=ключ)
    return out


async def карточка_клиента(session: AsyncSession, client_id: int, админ: str | None = None) -> dict | None:
    """Полная карточка обзвона для любого клиента базы.

    Если он в сегодняшней очереди — карточка его задачи. Если нет — «пустая»
    задача без id: скрипт по его сегменту, кнопки работают через open.
    """
    from types import SimpleNamespace

    today = moscow_today()
    client = await session.get(Client, client_id)
    if client is None:
        return None
    задача = (await session.execute(
        select(ContactTask).where(ContactTask.client_id == client_id, ContactTask.due_date == today)
        .order_by(ContactTask.status.desc())
    )).scalars().first()
    if задача is None:
        группа = _группа_клиента((await get_completed_visit_dates(session)).get(client_id, []), today)
        группа = группа if группа in ACTIONABLE_SEGMENTS else ГРУППА_ПОИСК
        задача = SimpleNamespace(id=None, group_code=группа, priority=TASK_PRIORITY.get(группа, 1),
                                 due_date=today, status="none", script_version="v1")
    # Клиент с тегом «не звонить по обзвону» (Переехал и т.п.) из очереди
    # исключён, но из базы его карточку открыть можно — хотя бы чтобы снять
    # тег. Раньше такой клиент ронял запрос (пустой список → [0]), и карточка
    # вечно грузилась: «находит, грузит и пропадает» (Иван, 02.11.2026).
    return (await _карточки(session, [(задача, client)], админ, today, исключать=False))[0]


async def open_from_search(session: AsyncSession, client_id: int) -> dict:
    """Поставить найденного клиента в сегодняшнюю очередь и вернуть задачу.

    Если задача на сегодня уже есть — она и возвращается. Группа берётся по
    сегменту клиента: так у потерянного будет скрипт возврата и звонок
    засчитается в «Возвращённые».
    """
    today = moscow_today()
    if await session.get(Client, client_id) is None:
        return {"ok": False, "error": "клиент не найден"}
    есть = (await session.execute(
        select(ContactTask).where(ContactTask.client_id == client_id, ContactTask.due_date == today)
        .order_by(ContactTask.status)  # open раньше done
    )).scalars().first()
    if есть is not None:
        return {"ok": True, "task_id": есть.id}
    сегмент = (compute_segment((await get_completed_visit_dates(session)).get(client_id, []), today) or {}).get("segment")
    группа = сегмент if сегмент in ACTIONABLE_SEGMENTS else ГРУППА_ПОИСК
    task = ContactTask(client_id=client_id, group_code=группа, priority=TASK_PRIORITY[группа],
                       due_date=today, status="open", script_version=ИЗ_ПОИСКА)
    session.add(task)
    await session.commit()
    return {"ok": True, "task_id": task.id}


async def refresh_tasks(session: AsyncSession) -> dict:
    """Regenerate today's contact queue from actionable segments (no duplicates)."""
    profiles = await build_client_profiles(session)
    today = moscow_today()

    # «Теряем сегодня»: сегодня 60-й день без визита и нет записи вперёд.
    # Если дозвониться и записать сегодня, в статистику потерянных за день
    # клиент не попадёт (запрос владельца 29.10.2026) — поэтому он в очереди
    # всегда, даже если по личному ритму звонить ему ещё рано.
    теряем = теряем_сегодня(profiles, await _clients_with_future_booking(session), today)
    client_ids = [cid for cid, p in profiles.items()
                  if p["segment"] in ACTIONABLE_SEGMENTS or cid in теряем]
    clients = {}
    if client_ids:
        rows = await session.execute(select(Client).where(Client.id.in_(client_ids)))
        for c in rows.scalars().all():
            clients[c.id] = c
    # «НЕ ЗВОНИТЬ!» — такого клиента в очередь больше не ставим.
    не_звонить = {cid for cid, c in clients.items() if c.do_not_call}
    # Теги вроде «переехал» или «записывает супруга» — то же самое, но мягко:
    # тег снимается одним кликом (решение владельца 16.10.2026).
    не_звонить |= set(await excluded_by_tag(session))
    # Кому обещали перезвонить сегодня или раньше. Такой клиент попадает в
    # очередь, даже если по сегментам звонить его повода нет.
    перезвон = set((await session.execute(
        select(Client.id).where(
            Client.next_contact_at.is_not(None),
            Client.next_contact_at <= today,
            Client.do_not_call.is_(False),
        )
    )).scalars())
    # С кем сегодня уже говорили: задача на него осталась в списке со своим
    # исходом, и вторая, пустая, рядом с ней была бы той же строкой дважды.
    сегодня_закрыты = set((await session.execute(
        select(ContactTask.client_id).where(
            ContactTask.due_date == today, ContactTask.status == "done"
        )
    )).scalars())

    # Клиент, открытый админом из поиска, живёт в очереди до конца дня:
    # пересборка идёт при каждой выгрузке и иначе стирала бы его.
    из_поиска = set((await session.execute(
        select(ContactTask.client_id).where(
            ContactTask.script_version == ИЗ_ПОИСКА,
            ContactTask.due_date == today,
            ContactTask.status == "open",
        )
    )).scalars())
    сегодня_закрыты |= из_поиска

    # Remove all still-open tasks (idempotent daily refresh — old days' tasks are stale).
    from sqlalchemy import and_, delete, not_
    await session.execute(
        delete(ContactTask).where(
            ContactTask.status == "open",
            not_(and_(ContactTask.script_version == ИЗ_ПОИСКА, ContactTask.due_date == today)),
        )
    )

    created = 0
    for cid in sorted(перезвон - не_звонить - сегодня_закрыты - set(profiles)):
        # Клиент не в рабочем сегменте, но обещание перезвонить важнее.
        session.add(ContactTask(client_id=cid, group_code="callback",
                                priority=TASK_PRIORITY["callback"], due_date=today,
                                status="open", script_version="v1"))
        created += 1
    for cid, p in profiles.items():
        if cid in не_звонить or cid in сегодня_закрыты:
            continue
        группа = "callback" if cid in перезвон else p["segment"]
        if группа != "callback" and p["segment"] not in ACTIONABLE_SEGMENTS:
            if cid not in теряем:
                continue
            группа = ГРУППА_ТЕРЯЕМ
        task = ContactTask(
            client_id=cid,
            group_code=группа,
            priority=TASK_PRIORITY.get(группа, 1),
            due_date=today,
            status="open",
            script_version="v1",
        )
        session.add(task)
        created += 1

    await session.commit()
    return {"tasks_created": created, "date": today.isoformat()}


# --------------------------------------------------------------------------- #
# Теги, скрипты и плановый перезвон (запрос владельца 16.10.2026)
# --------------------------------------------------------------------------- #

# Регламент возврата из файла владельца (16.10.2026). Разговор — дерево:
# начало → причина ухода → завершение; отдельно сообщение, если не ответил.
# Это значения по умолчанию: любой вариант правится в Настройках, пустое
# поле возвращает текст отсюда.
ВАРИАНТЫ_ВОЗВРАТА = [
    ("start", "Начало разговора", """Здравствуйте, {имя}! Это {админ}, барбершоп «РублЪ».
Вы раньше посещали нас, и мы связываемся с гостями, которых давно не было. Нам важно поддерживать качество сервиса и понимать, что мы можем сделать лучше.
Подскажите, как у вас дела? И можно задать один небольшой вопрос: по какой причине вы перестали к нам ходить?""",
     "Задали вопрос — сделайте паузу. Не переходите сразу к записи."),
    ("quality", "Не понравилась работа", """Спасибо, что сказали нам об этом. Нам очень жаль, что у вас осталось такое впечатление — мы хотим, чтобы каждый гость оставался доволен результатом.
Подскажите, что именно вам не понравилось? Для нас важно разобраться и не допустить повторения.
Я обязательно передам ваши замечания руководителю.""",
     "Зафиксируйте детали, дату визита и мастера. Передайте руководителю. Индивидуальные решения — только после согласования."),
    ("price", "Дорого", """Понимаю вас, спасибо, что поделились. Подскажите, дело именно в стоимости услуги или в том, что соотношение цены и результата перестало устраивать?
Мы хотим, чтобы гости понимали, за что платят, и получали достойный результат.""",
     "Уточните ожидания. Про действующие предложения — только если подходят. Скидку без согласования не обещать."),
    ("time", "Неудобно записываться", """Понимаю, график бывает плотным. Подскажите, было сложно подобрать удобное время или не получалось попасть к конкретному мастеру?
Мы можем подобрать время и заранее запланировать следующий визит.""",
     "Предложите свободные слоты, другого подходящего мастера или предварительную запись."),
    ("moved", "Далеко / переехал", """Понимаю, расположение действительно имеет значение. Спасибо, что раньше выбирали нас!
Если будете бывать рядом — будем рады видеть снова. А если есть что-то ещё, что повлияло на решение, с удовольствием выслушаем.""",
     "Не давите на запись. Поставьте тег «Переехал»."),
    ("other_barber", "Ушёл к другому мастеру", """Понимаю, главное — найти мастера, результатом которого вы довольны. Спасибо, что были нашим гостем.
Если вам комфортно ответить: чего вам не хватало у нас или что понравилось в другом месте? Нам важно понимать, в чём мы можем стать лучше.""",
     "Уточните, что важно клиенту: техника, общение, стабильность, атмосфера, удобство записи. Другого мастера не критиковать."),
    ("conflict", "Конфликт или плохой сервис", """Спасибо, что рассказали. Мне жаль, что возникла такая ситуация — мы не хотим, чтобы гости уходили с таким впечатлением.
Не буду оправдываться, мне важно понять, что произошло. Расскажите, пожалуйста, подробнее. Я зафиксирую обращение и передам руководителю.""",
     "Не спорить и не обвинять. Зафиксируйте факты, передайте руководителю, договоритесь, кто и когда даст клиенту ответ."),
    ("just_long", "Просто давно не заходил", """Понял вас, спасибо! Тогда будем рады видеть вас снова в «РублЪ».
Если планируете обновить стрижку, помогу подобрать удобное время и мастера. Вам актуально записаться на ближайшие дни?""",
     "Если клиент не готов — не настаивайте. Зафиксируйте договорённость."),
    ("finish", "Завершение и запись", """{имя}, спасибо за обратную связь. Нам важно не просто возвращать гостей, а делать так, чтобы к нам хотелось приходить.
Будем рады снова увидеть вас в «РублЪ». Давайте подберём удобное время — могу предложить несколько вариантов.""",
     "Если проблема серьёзная — сначала решаем её. Не торопите с записью, пока человек не почувствовал, что его услышали."),
]

СООБЩЕНИЕ_БЕЗ_ОТВЕТА = """Здравствуйте, {имя}! Это барбершоп «РублЪ» 👋
Давно не виделись и решили поинтересоваться, как у вас дела. Нам важно мнение гостей: возможно, изменились обстоятельства или что-то в нашей работе было не таким, как хотелось бы.
Будем рады видеть вас снова!"""

# Три варианта на каждую «живую» группу: коротко, по делу и с заботой.
ВАРИАНТЫ_ГРУПП: dict[str, list[tuple[str, str, str, str]]] = {
    "due": [
        ("short", "Коротко", "Здравствуйте, {имя}! Это барбершоп «РублЪ». Подскажите, когда вам удобно записаться?",
         "{имя}, здравствуйте! Подобрать вам время на этой неделе?", ""),
        ("master", "Через мастера", "Здравствуйте, {имя}! У {мастер} освободилось время на этой неделе — забронировать за вами?",
         "{имя}, здравствуйте! У {мастер} есть окно на этой неделе — забронировать?", "Называйте мастера, у которого клиент стрижётся обычно."),
        ("care", "С заботой", "Здравствуйте, {имя}! Прошло уже {дней_без_визита} дней с прошлой стрижки — обычно вы приходите чаще. Всё в порядке?",
         "{имя}, здравствуйте! Давно вас не видели — всё ли хорошо?", "Сначала выслушайте ответ, потом предлагайте время."),
    ],
    "risk": [
        ("short", "Коротко", "Здравствуйте, {имя}! Вы давно у нас не были. Удобно записаться на этой неделе?",
         "{имя}, здравствуйте! Будем рады видеть вас снова — подобрать время?", ""),
        ("feedback", "Спросить, как всё прошло", "Здравствуйте, {имя}! Хотел узнать, всё ли понравилось в прошлый раз у {мастер}?",
         "{имя}, здравствуйте! Всё ли было хорошо в прошлый раз?", "Если есть замечание — зафиксируйте и передайте руководителю."),
        ("offer", "С предложением времени", "Здравствуйте, {имя}! Освободилось удобное время — вечер буднего дня. Вам подойдёт?",
         "{имя}, здравствуйте! Есть вечернее время на этой неделе — забронировать?", "Называйте конкретные слоты, так проще согласиться."),
    ],
    "late": [
        ("short", "Коротко", "Здравствуйте, {имя}! Давно не виделись. Всё ли было хорошо в прошлый раз?",
         "{имя}, здравствуйте! Если что-то было не так — расскажите, мы исправим.", ""),
        ("reason", "Выяснить причину", "Здравствуйте, {имя}! Вы давно не заходили — подскажите, дело в расписании или в чём-то другом?",
         "{имя}, здравствуйте! Подскажите, что нам стоит улучшить?", "Дайте договорить, не перебивайте."),
        ("care", "С заботой", "Здравствуйте, {имя}! Прошло {дней_без_визита} дней — мы скучаем. Помочь подобрать время?",
         "{имя}, здравствуйте! Прошло уже много времени — будем рады видеть снова.", ""),
    ],
    "callback": [
        ("short", "Коротко", "Здравствуйте, {имя}! Обещал перезвонить — подобрать вам время?",
         "{имя}, здравствуйте! Как договаривались, напоминаю о себе.", ""),
        ("deal", "По договорённости", "Здравствуйте, {имя}! В прошлый раз договаривались созвониться сегодня. Удобно сейчас говорить?",
         "{имя}, здравствуйте! Мы договаривались связаться — вам удобно обсудить запись?", "Начните с того, о чём договорились в прошлый раз."),
    ],
}


# «Теряем сегодня» и «Из поиска» — свои слова не нужны: первые по сути в зоне
# риска, вторым подходит обычное «пора записываться».
ВАРИАНТЫ_ГРУПП["losing"] = ВАРИАНТЫ_ГРУПП["risk"]
ВАРИАНТЫ_ГРУПП["manual"] = ВАРИАНТЫ_ГРУПП["due"]
TASK_SCRIPTS["losing"] = {**TASK_SCRIPTS["risk"], "goal": "Записать сегодня — завтра клиент станет потерянным"}
TASK_SCRIPTS["manual"] = TASK_SCRIPTS["due"]


def варианты_по_умолчанию(группа: str) -> list[dict]:
    """Готовые варианты разговора для группы обзвона."""
    if группа == "lost":
        строки = [{"variant": код, "title": название, "phone": текст,
                   "message": СООБЩЕНИЕ_БЕЗ_ОТВЕТА if код == "start" else "", "hint": подсказка}
                  for код, название, текст, подсказка in ВАРИАНТЫ_ВОЗВРАТА]
        return строки
    return [{"variant": код, "title": название, "phone": звонок, "message": сообщение, "hint": подсказка}
            for код, название, звонок, сообщение, подсказка in ВАРИАНТЫ_ГРУПП.get(группа, [])]


ГРУППЫ_ОБЗВОНА = {
    "due": "Пора записываться",
    "risk": "Зона риска",
    "late": "Сильно задерживаются",
    "lost": "Потерянные",
    "callback": "Перезвонить",
}

СТАРТОВЫЕ_ТЕГИ = [
    # (код, название, цвет, исключать из обзвона, акционный)
    ("moved", "Переехал", "#a83329", True, False),
    ("spouse_books", "Записывает супруга", "#9a6a36", True, True),
    ("promo", "Акция", "#1f6e41", False, True),
    ("no_reply", "Не реагирует", "#8a6412", False, False),
]


async def ensure_tags(session: AsyncSession) -> list[ClientTag]:
    """Первый заход — заводим четыре стартовых тега, дальше их правит владелец."""
    теги = list((await session.execute(select(ClientTag).order_by(ClientTag.sort, ClientTag.id))).scalars())
    if теги:
        return теги
    for i, (код, имя, цвет, исключать, акция) in enumerate(СТАРТОВЫЕ_ТЕГИ):
        session.add(ClientTag(code=код, name=имя, color=цвет,
                              exclude_from_calls=исключать, promo=акция, sort=i))
    await session.commit()
    return list((await session.execute(select(ClientTag).order_by(ClientTag.sort, ClientTag.id))).scalars())


def _тег_в_словарь(t: ClientTag, сколько: int | None = None) -> dict:
    итог = {"id": t.id, "code": t.code, "name": t.name, "color": t.color,
            "exclude_from_calls": t.exclude_from_calls, "promo": t.promo, "sort": t.sort}
    if сколько is not None:
        итог["clients"] = сколько
    return итог


async def tags_list(session: AsyncSession) -> list[dict]:
    теги = await ensure_tags(session)
    счёт = dict((await session.execute(
        select(ClientTagLink.tag_id, func.count()).group_by(ClientTagLink.tag_id)
    )).all())
    return [_тег_в_словарь(t, int(счёт.get(t.id, 0))) for t in теги]


async def save_tag(session: AsyncSession, данные: dict) -> dict:
    """Создать или поправить тег. Код задаём сами — по нему живут скрипты."""
    тег = await session.get(ClientTag, данные["id"]) if данные.get("id") else None
    if тег is None:
        код = (данные.get("code") or "").strip() or f"tag{int(datetime.now(MOSCOW).timestamp())}"
        тег = ClientTag(code=код, name=данные.get("name") or код, sort=данные.get("sort") or 0)
        session.add(тег)
    if данные.get("name"):
        тег.name = данные["name"]
    for поле in ("color", "exclude_from_calls", "promo", "sort"):
        if поле in данные and данные[поле] is not None:
            setattr(тег, поле, данные[поле])
    await session.commit()
    return _тег_в_словарь(тег)


async def delete_tag(session: AsyncSession, tag_id: int) -> dict:
    from sqlalchemy import delete as _delete

    тег = await session.get(ClientTag, tag_id)
    if тег is None:
        return {"ok": True}
    await session.execute(_delete(ClientTagLink).where(ClientTagLink.tag_id == tag_id))
    await session.execute(_delete(Script).where(Script.kind == "tag", Script.key == тег.code))
    await session.delete(тег)
    await session.commit()
    return {"ok": True}


async def set_client_tag(session: AsyncSession, client_id: int, tag_id: int,
                         value: bool, actor: str | None) -> dict:
    """Повесить или снять тег. Повторное навешивание ничего не ломает."""
    from sqlalchemy import delete as _delete

    есть = await session.scalar(select(ClientTagLink).where(
        ClientTagLink.client_id == client_id, ClientTagLink.tag_id == tag_id))
    if value and есть is None:
        session.add(ClientTagLink(client_id=client_id, tag_id=tag_id, created_by=actor))
    elif not value and есть is not None:
        await session.execute(_delete(ClientTagLink).where(ClientTagLink.id == есть.id))
    await session.commit()
    return {"ok": True, "client_id": client_id, "tag_id": tag_id, "value": value}


async def tags_by_client(session: AsyncSession, client_ids: list[int]) -> dict[int, list[dict]]:
    if not client_ids:
        return {}
    строки = (await session.execute(
        select(ClientTagLink.client_id, ClientTag)
        .join(ClientTag, ClientTag.id == ClientTagLink.tag_id)
        .where(ClientTagLink.client_id.in_(client_ids))
        .order_by(ClientTag.sort, ClientTag.id)
    )).all()
    итог: dict[int, list[dict]] = defaultdict(list)
    for cid, тег in строки:
        итог[cid].append(_тег_в_словарь(тег))
    return dict(итог)


async def excluded_by_tag(session: AsyncSession) -> dict[int, str]:
    """client_id → название тега, который убирает его из обзвона."""
    строки = (await session.execute(
        select(ClientTagLink.client_id, ClientTag.name)
        .join(ClientTag, ClientTag.id == ClientTagLink.tag_id)
        .where(ClientTag.exclude_from_calls.is_(True))
    )).all()
    return {cid: имя for cid, имя in строки}


ПОДСТАНОВКИ = ("{имя}", "{мастер}", "{услуга}", "{дней_без_визита}", "{админ}")


def подставить(текст: str, имя: str | None, мастер: str | None,
               услуга: str | None, дней: int | None, админ: str | None = None) -> str:
    """Подстановки в скрипт. Старое {name} поддерживаем — так написаны зашитые."""
    замены = {
        "{name}": имя or "", "{имя}": имя or "",
        "{мастер}": мастер or "мастер", "{услуга}": услуга or "услуга",
        "{дней_без_визита}": str(дней) if дней is not None else "—",
        "{админ}": админ or "администратор",
    }
    for ключ, значение in замены.items():
        текст = текст.replace(ключ, значение)
    return текст


async def scripts_map(session: AsyncSession) -> dict[tuple[str, str], list[Script]]:
    """(kind, key) → варианты разговора, в порядке показа."""
    строки = list((await session.execute(
        select(Script).order_by(Script.sort, Script.id))).scalars())
    итог: dict[tuple[str, str], list[Script]] = defaultdict(list)
    for s_ in строки:
        итог[(s_.kind, s_.key)].append(s_)
    return dict(итог)


def _варианты(kind: str, key: str, свои: list[Script], готовые: list[dict]) -> list[dict]:
    """Склейка: готовые варианты из регламента + заведённые руками."""
    по_коду = {s_.variant: s_ for s_ in свои}
    строки: list[dict] = []
    for i, в in enumerate(готовые):
        s_ = по_коду.pop(в["variant"], None)
        строки.append({
            "kind": kind, "key": key, "variant": в["variant"],
            "title": (s_.title if s_ and s_.title else в["title"]),
            "hint": (s_.hint if s_ and s_.hint else в.get("hint", "")),
            "phone_text": s_.phone_text if s_ else None,
            "message_text": s_.message_text if s_ else None,
            "default_phone": в.get("phone", ""), "default_message": в.get("message", ""),
            "custom": False, "sort": s_.sort if s_ else i,
            "updated_by": s_.updated_by if s_ else None,
        })
    for s_ in по_коду.values():  # варианты, которых в регламенте нет
        строки.append({
            "kind": kind, "key": key, "variant": s_.variant,
            "title": s_.title or s_.variant, "hint": s_.hint or "",
            "phone_text": s_.phone_text, "message_text": s_.message_text,
            "default_phone": "", "default_message": "", "custom": True,
            "sort": s_.sort, "updated_by": s_.updated_by,
        })
    строки.sort(key=lambda в: в["sort"])
    return строки


async def scripts_all(session: AsyncSession) -> dict:
    """Страница «Скрипты обзвона»: варианты разговора по группам и тегам."""
    карта = await scripts_map(session)
    теги = await ensure_tags(session)
    return {
        "placeholders": list(ПОДСТАНОВКИ),
        "groups": [{"kind": "group", "key": код, "label": ГРУППЫ_ОБЗВОНА.get(код, код),
                    "variants": _варианты("group", код, карта.get(("group", код), []),
                                          варианты_по_умолчанию(код))}
                   for код in ACTIONABLE_SEGMENTS + ["callback"]],
        "tags": [{"kind": "tag", "key": т.code, "label": т.name,
                  "variants": _варианты("tag", т.code, карта.get(("tag", т.code), []), [])}
                 for т in теги],
    }


async def save_script(session: AsyncSession, kind: str, key: str,
                      phone_text: str | None, message_text: str | None,
                      actor: str | None, variant: str = "main",
                      title: str | None = None, hint: str | None = None) -> dict:
    if kind not in ("group", "tag"):
        return {"ok": False, "error": "unknown kind"}
    variant = (variant or "main").strip()[:40]
    s_ = await session.scalar(select(Script).where(
        Script.kind == kind, Script.key == key, Script.variant == variant))
    if s_ is None:
        s_ = Script(kind=kind, key=key, variant=variant,
                    sort=await session.scalar(select(func.count()).where(
                        Script.kind == kind, Script.key == key)) or 0)
        session.add(s_)
    if title is not None:
        s_.title = title.strip()[:80] or None
    if hint is not None:
        s_.hint = hint.strip() or None
    # Пустое поле = «вернуть стандартный текст», поэтому пустую строку храним
    # как NULL, а не как пустой скрипт.
    s_.phone_text = (phone_text or "").strip() or None
    s_.message_text = (message_text or "").strip() or None
    s_.updated_at = datetime.now(MOSCOW)
    s_.updated_by = actor
    await session.commit()
    return {"ok": True, "kind": kind, "key": key, "variant": variant}


async def delete_script(session: AsyncSession, kind: str, key: str, variant: str) -> dict:
    """Убрать свой вариант. Вариант из регламента вернётся стандартным текстом."""
    from sqlalchemy import delete as _delete

    await session.execute(_delete(Script).where(
        Script.kind == kind, Script.key == key, Script.variant == variant))
    await session.commit()
    return {"ok": True}


ЛОЯЛЬНОСТЬ = ("green", "yellow", "red")


async def set_loyalty(session: AsyncSession, client_id: int, value: str | None,
                      actor: str | None) -> dict:
    """Светофор лояльности: как клиент держался в разговоре."""
    if value is not None and value not in ЛОЯЛЬНОСТЬ:
        return {"ok": False, "error": "неизвестный цвет"}
    client = await session.get(Client, client_id)
    if client is None:
        return {"ok": False, "error": "client not found"}
    # Повторное нажатие той же лампочки гасит светофор — иначе ошибку не снять.
    client.loyalty = None if client.loyalty == value else value
    client.loyalty_at = datetime.now(MOSCOW) if client.loyalty else None
    client.loyalty_by = actor if client.loyalty else None
    await session.commit()
    return {"ok": True, "client_id": client_id, "loyalty": client.loyalty}


async def set_next_contact(session: AsyncSession, client_id: int, when: date | None,
                           note: str | None, actor: str | None) -> dict:
    client = await session.get(Client, client_id)
    if client is None:
        return {"ok": False, "error": "client not found"}
    client.next_contact_at = when
    client.next_contact_note = (note or "").strip()[:200] or None
    client.next_contact_by = actor if when else None
    await session.commit()
    return {"ok": True, "client_id": client_id,
            "next_contact_at": when.isoformat() if when else None,
            "next_contact_note": client.next_contact_note}


async def contact_counters(session: AsyncSession, client_ids: list[int]) -> dict[int, dict]:
    """Сколько раз с клиентом связывались: всего, за год, сколько записей."""
    if not client_ids:
        return {}
    год_назад = datetime.now(MOSCOW) - timedelta(days=365)
    строки = (await session.execute(
        select(ContactTask.client_id, ContactAttempt.outcome, ContactAttempt.created_at)
        .join(ContactTask, ContactTask.id == ContactAttempt.task_id)
        .where(ContactTask.client_id.in_(client_ids))
    )).all()
    итог: dict[int, dict] = defaultdict(lambda: {"total": 0, "year": 0, "booked": 0})
    for cid, outcome, когда in строки:
        c = итог[cid]
        c["total"] += 1
        if outcome == "booked":
            c["booked"] += 1
        if когда is not None:
            когда = когда if когда.tzinfo else когда.replace(tzinfo=MOSCOW)
            if когда >= год_назад:
                c["year"] += 1
    return dict(итог)


async def last_master_map(session: AsyncSession, client_ids: list[int]) -> dict[int, dict]:
    """client_id → мастер последнего завершённого визита (решение владельца 16.10)."""
    if not client_ids:
        return {}
    строки = (await session.execute(
        select(Visit.client_id, Visit.datetime, Employee.yclients_id, Employee.name)
        .join(Employee, Employee.id == Visit.employee_id)
        .where(Visit.client_id.in_(client_ids), Visit.status == "completed")
        .order_by(Visit.client_id, Visit.datetime.desc())
    )).all()
    итог: dict[int, dict] = {}
    for cid, _дата, staff_id, имя in строки:
        if cid not in итог:
            итог[cid] = {"staff_id": int(staff_id), "name": имя}
    return итог


async def services_map(session: AsyncSession, client_ids: list[int], визитов: int = 3) -> dict[int, list[str]]:
    """Услуги последних визитов клиента — для фильтра очереди по услуге."""
    if not client_ids:
        return {}
    строки = (await session.execute(
        select(Visit.client_id, Visit.datetime, VisitService.title)
        .join(VisitService, VisitService.visit_id == Visit.id)
        .where(Visit.client_id.in_(client_ids), Visit.status == "completed")
        .order_by(Visit.client_id, Visit.datetime.desc())
    )).all()
    визиты: dict[int, set] = defaultdict(set)
    итог: dict[int, list[str]] = defaultdict(list)
    for cid, когда, название in строки:
        if название is None:
            continue
        визиты[cid].add(когда)
        if len(визиты[cid]) > визитов:
            continue
        if название not in итог[cid]:
            итог[cid].append(название)
    return dict(итог)


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


def _скрипты_задачи(task, client, скрипты: dict, теги: list[dict], по_умолчанию: dict,
                    мастер: dict | None, услуги: list[str] | None, дней: int | None,
                    админ: str | None = None) -> dict:
    """Варианты разговора для карточки: сначала тег, потом группа.

    Скрипт возврата — это дерево (регламент салона): начало, ветка по причине
    ухода, завершение. Поэтому карточка получает список вариантов, а не один
    текст, и админ переключает их прямо во время разговора.
    """
    имя_мастера = (мастер or {}).get("name")
    услуга = (услуги or [None])[0]

    def готовые(kind: str, key: str) -> list[dict]:
        свои = скрипты.get((kind, key), [])
        основа = варианты_по_умолчанию(key) if kind == "group" else []
        return _варианты(kind, key, свои, основа)

    выбранный_тег = next((t for t in теги if скрипты.get(("tag", t["code"]))), None)
    источник = "default"
    строки = готовые("group", task.group_code)
    if выбранный_тег is not None:
        из_тега = готовые("tag", выбранный_тег["code"])
        if из_тега:
            строки = из_тега + строки
            источник = "tag:" + выбранный_тег["code"]
    elif скрипты.get(("group", task.group_code)):
        источник = "group"

    варианты = []
    for в in строки:
        звонок = в["phone_text"] or в["default_phone"]
        сообщение = в["message_text"] or в["default_message"]
        if not звонок and not сообщение:
            continue
        варианты.append({
            "variant": в["variant"], "title": в["title"], "hint": в["hint"],
            "phone": подставить(звонок, client.name, имя_мастера, услуга, дней, админ),
            "message": подставить(сообщение, client.name, имя_мастера, услуга, дней, админ),
        })
    if not варианты:  # ни регламента, ни своих — зашитый в коде текст
        варианты = [{
            "variant": "main", "title": "Скрипт", "hint": "",
            "phone": подставить(по_умолчанию.get("phone", ""), client.name, имя_мастера, услуга, дней, админ),
            "message": подставить(по_умолчанию.get("message", ""), client.name, имя_мастера, услуга, дней, админ),
        }]
    return {
        "scripts": варианты,
        "phone_script": варианты[0]["phone"],
        "message_script": next((в["message"] for в in варианты if в["message"]), ""),
        "script_source": источник,
    }


async def get_tasks(session: AsyncSession, status: str = "open",
                    админ: str | None = None) -> list[dict]:
    """Очередь обзвона на сегодня.

    status="open" отдаёт весь сегодняшний список, включая уже обработанных:
    раньше клиент исчезал сразу после нажатия, и администратор не видел ни
    что он сделал, ни кого осталось обзвонить (решение владельца 11.10.2026).
    Обработанные уходят вниз — порядок задаёт сортировка в конце.
    """
    today = moscow_today()
    cond = ContactTask.status == status
    if status == "open":
        # Очередь — на сегодня, вместе с уже закрытыми сегодня задачами.
        cond = ContactTask.due_date == today
    rows = await session.execute(
        select(ContactTask, Client)
        .join(Client, Client.id == ContactTask.client_id)
        .where(cond)
        .order_by(ContactTask.due_date.desc(), ContactTask.priority.desc())
    )
    pairs = [(task, client) for task, client in rows.all()]
    out = await _карточки(session, pairs, админ, today)
    # Порядок (решение владельца 16.10.2026): обещанный перезвон на сегодня →
    # необзвонённые по важности сегмента → запланированные на будущее →
    # обзвонённые сегодня, самые давние выше.
    out.sort(key=ключ_очереди)
    return out


def ключ_очереди(t: dict) -> tuple:
    обзвонён = t["called_today"]
    запланирован_позже = bool(t["next_contact_at"]) and not t["callback_due"]
    ступень = 3 if обзвонён else (
        -1 if t["lost_today"] else 2 if запланирован_позже else (0 if t["callback_due"] else 1))
    return (ступень, t["next_contact_at"] or "", -t["priority"], t["last_call_at"] or "")


async def _карточки(session: AsyncSession, pairs: list, админ: str | None, today: date,
                    исключать: bool = True) -> list[dict]:
    """Карточки обзвона для пар (задача, клиент). Задача может быть «пустой»
    (SimpleNamespace без id) — карточка клиента из базы, не из очереди."""
    client_ids = [c.id for _, c in pairs]
    dates_map = await get_completed_visit_dates(session)
    last_service_map = await get_last_service_map(session, client_ids)
    теги_клиентов = await tags_by_client(session, client_ids)
    мастера = await last_master_map(session, client_ids)
    услуги = await services_map(session, client_ids)
    счётчики = await contact_counters(session, client_ids)
    скрипты = await scripts_map(session)
    исключённые = await excluded_by_tag(session)
    с_записью = await _clients_with_future_booking(session)

    out = []
    for task, client in pairs:
        if исключать and client.id in исключённые:
            continue  # тег повесили уже после пересборки очереди
        dates = dates_map.get(client.id, [])
        script = TASK_SCRIPTS.get(task.group_code, {})
        звонок = client.last_call_at
        if звонок is not None:
            звонок = звонок.astimezone(MOSCOW) if звонок.tzinfo else звонок.replace(tzinfo=MOSCOW)
        out.append({
            "last_call_at": звонок.isoformat() if звонок else None,
            "last_call_outcome": client.last_call_outcome,
            "called_today": bool(звонок and звонок.date() == today),
            "id": task.id,
            "client_id": client.id,
            "client_name": client.name,
            "phone": client.phone,
            "yclients_url": ссылка_yclients(client.phone),
            "group_code": task.group_code,
            "priority": task.priority,
            "due_date": task.due_date.isoformat(),
            "status": task.status,
            "script_version": task.script_version,
            "visits_count": len(dates),
            "last_visit": dates[-1].isoformat() if dates else None,
            "days_since_visit": (today - dates[-1]).days if dates else None,
            "future_booking": client.id in с_записью,
            "lost_today": bool(dates) and (today - dates[-1]).days == LOST_AFTER_DAYS
                          and client.id not in с_записью,
            "last_service": last_service_map.get(client.id),
            "goal": script.get("goal", ""),
            **_скрипты_задачи(task, client, скрипты, теги_клиентов.get(client.id, []),
                              script, мастера.get(client.id), услуги.get(client.id),
                              (today - dates[-1]).days if dates else None, админ),
            "call_status": client.call_status,
            "last_call_by": client.last_call_by,
            "days_since_call": (today - звонок.date()).days if звонок else None,
            "loyalty": client.loyalty,
            "admin_note": client.admin_note,
            "tags": теги_клиентов.get(client.id, []),
            "last_master": мастера.get(client.id),
            "services": услуги.get(client.id, []),
            "contacts": счётчики.get(client.id, {"total": 0, "year": 0, "booked": 0}),
            "next_contact_at": client.next_contact_at.isoformat() if client.next_contact_at else None,
            "next_contact_note": client.next_contact_note,
            "callback_due": bool(client.next_contact_at and client.next_contact_at <= today),
        })
    return out


# --------------------------------------------------------------------------- #
# Возвращённые: кого обзвон поднял из потерянных (решение владельца 11.10.2026)
# --------------------------------------------------------------------------- #
#
# Данные клиентов — имя и телефон — остаются только в этой базе, на этом
# компьютере. На общий сервер уходят лишь расчётные показатели (см. hub.py:
# смены, остатки, отчёты банка), клиентов там нет и быть не должно.

ВОЗВРАТ_ПОДТВЕРЖДЁН = "confirmed"


async def calls_on(session: AsyncSession, день: date) -> dict[str, int]:
    """Обзвон за день для отчёта о закрытии смены: звонки, записи, возвраты."""
    начало = datetime.combine(день, datetime.min.time(), tzinfo=MOSCOW)
    строки = (await session.execute(
        select(ContactAttempt.outcome, ContactAttempt.was_lost).where(
            ContactAttempt.created_at >= начало,
            ContactAttempt.created_at < начало + timedelta(days=1),
        )
    )).all()
    записались = [x for x in строки if x[0] == "booked"]
    return {
        "total": len(строки),
        "booked": len(записались),
        "returned": sum(1 for x in записались if x[1]),
    }


async def returned_clients(session: AsyncSession, month: str | None = None) -> dict:
    """Кого вернули с начала месяца: статистика, график по дням и список.

    Возвращённый — нажатие «Записан» на клиенте, который в тот момент был
    потерянным. Подтверждение берётся из сверки с YCLIENTS (verify_pending):
    зелёная галочка — запись в сервисе нашлась, красный крестик — нет.
    """
    today = moscow_today()
    ym = month or today.strftime("%Y-%m")
    year, mon = (int(x) for x in ym.split("-"))
    first = date(year, mon, 1)
    last = date(year + (mon == 12), mon % 12 + 1, 1)
    начало = datetime.combine(first, datetime.min.time(), tzinfo=MOSCOW)
    конец = datetime.combine(last, datetime.min.time(), tzinfo=MOSCOW)

    строки = (await session.execute(
        select(ContactAttempt, Client)
        .join(ContactTask, ContactAttempt.task_id == ContactTask.id)
        .join(Client, ContactTask.client_id == Client.id)
        .where(
            ContactAttempt.outcome == "booked",
            ContactAttempt.was_lost.is_(True),
            ContactAttempt.created_at >= начало,
            ContactAttempt.created_at < конец,
        )
        .order_by(ContactAttempt.created_at.desc())
    )).all()

    клиенты: list[dict] = []
    по_дням: dict[str, int] = defaultdict(int)
    по_админам: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    счёт = {"total": 0, "confirmed": 0, "not_confirmed": 0, "pending": 0}
    for попытка, клиент in строки:
        когда = попытка.created_at
        когда = когда.astimezone(MOSCOW) if когда.tzinfo else когда.replace(tzinfo=MOSCOW)
        день = когда.date().isoformat()
        админ = попытка.actor_id or "—"
        статус = попытка.verification_status or "pending"
        if статус not in счёт:
            статус = "pending"  # error и прочее — «ещё не подтверждено»
        счёт["total"] += 1
        счёт[статус] += 1
        по_дням[день] += 1
        по_админам[админ][день] += 1
        клиенты.append({
            "attempt_id": попытка.id,
            "client_id": клиент.id,
            "name": клиент.name,
            "phone": клиент.phone,
            "clicked_at": когда.isoformat(),
            "admin": админ,
            "status": статус,
            "note": попытка.verification_note,
        })

    дни = [(first + timedelta(days=n)).isoformat()
           for n in range((min(last, today + timedelta(days=1)) - first).days)]
    return {
        "month": ym,
        "totals": счёт,
        "days": [{"date": d, "count": по_дням.get(d, 0)} for d in дни],
        "admins": [
            {"name": имя, "total": sum(по.values()),
             "days": [{"date": d, "count": по.get(d, 0)} for d in дни]}
            for имя, по in sorted(по_админам.items(), key=lambda kv: -sum(kv[1].values()))
        ],
        "clients": клиенты,
    }


ИСХОДЫ = {
    "booked": "Записались",
    "callback": "Перезвонить",
    "no_booking": "Без записи",
    "no_answer": "Не дозвонились",
}


def _период(period: str, today: date) -> date:
    return {"week": today - timedelta(days=7), "month": today.replace(day=1),
            "quarter": today - timedelta(days=90)}.get(period, today.replace(day=1))


async def _обзвон_из_кэша(session: AsyncSession, с_даты: date) -> dict | None:
    """Аналитика обзвона, пришедшая с общего сервера.

    Нужна там, где своей базы звонков нет — например, владелец смотрит с
    другого компьютера. На сервере имён и телефонов нет, поэтому разворачиваем
    их здесь по yclients_id; кого не знаем, показываем как «Клиент #id».
    """
    import json

    row = await session.get(AppSetting, "hub_calls_cache")
    if row is None or not row.value:
        return None
    кэш = json.loads(row.value)
    записи = [з for месяц in кэш.values() for з in месяц
              if (з.get("at") or "")[:10] >= с_даты.isoformat()]
    if not записи:
        return None
    имена = {c.yclients_id: c for c in (await session.execute(select(Client))).scalars()}
    группы: dict[str, list[dict]] = {к: [] for к in ИСХОДЫ}
    админы: dict[str, int] = defaultdict(int)
    for i, з in enumerate(sorted(записи, key=lambda x: x.get("at") or "", reverse=True)):
        исход = з.get("outcome") if з.get("outcome") in ИСХОДЫ else "no_booking"
        клиент = имена.get(з.get("yclients_id"))
        админы[з.get("admin") or "—"] += 1
        группы[исход].append({
            "attempt_id": -i - 1,
            "client_id": клиент.id if клиент else None,
            "yclients_id": з.get("yclients_id"),
            "name": клиент.name if клиент else f"Клиент #{з.get('yclients_id')}",
            "phone": клиент.phone if клиент else None,
            "at": з.get("at"),
            "admin": з.get("admin") or "—",
            "group_code": з.get("group_code"),
            "was_lost": bool(з.get("was_lost")),
            "verification_status": з.get("verification"),
            "tags": [], "master": None, "services": [],
        })
    return {
        "period": "cache", "from": с_даты.isoformat(), "total": len(записи),
        "from_server": True,
        "by_admin": [{"name": и, "total": n} for и, n in sorted(админы.items(), key=lambda kv: -kv[1])],
        "groups": [{"code": к, "label": п, "items": группы[к]} for к, п in ИСХОДЫ.items()],
        "masters": [], "services": [],
    }


async def calls_feed(session: AsyncSession, period: str = "month") -> dict:
    """Вкладка «Обзвоны»: совершённые звонки по подгруппам результата.

    Имена и телефоны берутся из локальной базы и здесь же остаются — наружу
    (hub.py) уходит только yclients_id клиента и цифры.
    """
    today = moscow_today()
    начало = datetime.combine(_период(period, today), datetime.min.time(), tzinfo=MOSCOW)
    строки = (await session.execute(
        select(ContactAttempt, ContactTask, Client)
        .join(ContactTask, ContactTask.id == ContactAttempt.task_id)
        .join(Client, Client.id == ContactTask.client_id)
        .where(ContactAttempt.created_at >= начало)
        .order_by(ContactAttempt.created_at.desc())
    )).all()

    if not строки:
        кэш = await _обзвон_из_кэша(session, начало.date())
        if кэш is not None:
            return кэш

    client_ids = list({c.id for _, _, c in строки})
    теги = await tags_by_client(session, client_ids)
    мастера = await last_master_map(session, client_ids)
    услуги = await services_map(session, client_ids)

    группы: dict[str, list[dict]] = {к: [] for к in ИСХОДЫ}
    админы: dict[str, int] = defaultdict(int)
    for попытка, задача, клиент in строки:
        когда = попытка.created_at
        когда = когда.astimezone(MOSCOW) if когда.tzinfo else когда.replace(tzinfo=MOSCOW)
        исход = попытка.outcome if попытка.outcome in ИСХОДЫ else "no_booking"
        админы[попытка.actor_id or "—"] += 1
        группы[исход].append({
            "attempt_id": попытка.id,
            "client_id": клиент.id,
            "yclients_id": клиент.yclients_id,
            "name": клиент.name,
            "phone": клиент.phone,
            "at": когда.isoformat(),
            "admin": попытка.actor_id or "—",
            "group_code": задача.group_code,
            "was_lost": попытка.was_lost,
            "verification_status": попытка.verification_status,
            "tags": [т["name"] for т in теги.get(клиент.id, [])],
            "master": (мастера.get(клиент.id) or {}).get("name"),
            "services": услуги.get(клиент.id, []),
        })

    # Ещё две подгруппы — не результаты звонка, а состояние клиента: кому
    # обещали перезвонить и кто из обзвона исключён.
    перезвон = (await session.execute(
        select(Client).where(Client.next_contact_at.is_not(None))
        .order_by(Client.next_contact_at)
    )).scalars().all()
    исключённые = (await session.execute(
        select(Client, ClientTag.name)
        .join(ClientTagLink, ClientTagLink.client_id == Client.id)
        .join(ClientTag, ClientTag.id == ClientTagLink.tag_id)
        .where(ClientTag.exclude_from_calls.is_(True))
    )).all()

    def клиент_строкой(c: Client, причина: str | None = None) -> dict:
        return {"client_id": c.id, "yclients_id": c.yclients_id, "name": c.name,
                "phone": c.phone, "at": c.next_contact_at.isoformat() if c.next_contact_at else None,
                "note": c.next_contact_note, "reason": причина,
                "master": (мастера.get(c.id) or {}).get("name")}

    подгруппы = [
        {"code": код, "label": подпись, "items": группы[код]}
        for код, подпись in ИСХОДЫ.items()
    ] + [
        {"code": "planned", "label": "Ждут звонка по плану",
         "items": [клиент_строкой(c) for c in перезвон]},
        {"code": "excluded", "label": "Исключены из обзвона",
         "items": [клиент_строкой(c, причина) for c, причина in исключённые]
                  + [клиент_строкой(c, "НЕ ЗВОНИТЬ") for c in (await session.execute(
                      select(Client).where(Client.do_not_call.is_(True)))).scalars()],
        },
    ]
    return {
        "period": period,
        "from": начало.date().isoformat(),
        "total": len(строки),
        "by_admin": [{"name": и, "total": n} for и, n in sorted(админы.items(), key=lambda kv: -kv[1])],
        "groups": подгруппы,
        "masters": sorted({m["name"] for m in мастера.values() if m.get("name")}),
        "services": sorted({u for список in услуги.values() for u in список}),
    }


# Ссылка на клиента в YCLIENTS: база филиала с быстрым поиском по телефону.
# Карточку по номеру клиента веб-кабинет YCLIENTS не открывает — образец
# рабочего адреса прислал владелец 30.10.2026 (домен .ru, quick_search).
YCLIENTS_CLIENT_URL = (
    "https://yclients.ru/clients/{company}/base/?fields%5B0%5D=name&fields%5B1%5D=surname"
    "&fields%5B2%5D=phone&fields%5B3%5D=email&fields%5B4%5D=sold_amount&fields%5B5%5D=visits_count"
    "&fields%5B6%5D=discount&fields%5B7%5D=last_visit_date&fields%5B8%5D=first_visit_date"
    "&fields%5B9%5D=tips_count&order_by=id&order_by_direction=desc&page=1&page_size=25&segment="
    "&operation=AND&filters%5B0%5D%5Boperation%5D=OR&filters%5B0%5D%5Bfilters%5D%5B0%5D%5Boperation%5D=AND"
    "&filters%5B0%5D%5Bfilters%5D%5B0%5D%5Bfilters%5D%5B0%5D%5Boperation%5D=AND"
    "&filters%5B1%5D%5Btype%5D=quick_search&filters%5B1%5D%5Bstate%5D%5Bvalue%5D={phone}"
)


def шаблон_yclients() -> str | None:
    """Ссылка на поиск в YCLIENTS с местом ``{phone}`` под 8 и 10 цифр."""
    компания = settings.yclients_company_id
    return YCLIENTS_CLIENT_URL.replace("{company}", str(компания)) if компания else None


def ссылка_yclients(phone: str | None) -> str | None:
    """Телефон для поиска YCLIENTS — как его набирают в кабинете: 8 и 10 цифр."""
    компания = settings.yclients_company_id
    ц = цифры(phone)[-10:]
    return YCLIENTS_CLIENT_URL.format(company=компания, phone="8" + ц) if компания and len(ц) == 10 else None


def _в_москву(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return (dt.astimezone(MOSCOW) if dt.tzinfo else dt.replace(tzinfo=MOSCOW)).isoformat()


async def _звонки_других_компьютеров(session: AsyncSession, с: date | None, по: date | None,
                                     свои: list[dict]) -> list[dict]:
    """Звонки с других компьютеров (салон ↔ Мак владельца) через общий сервер.

    На сервере только номер клиента YCLIENTS и цифры; имя, телефон, хэштеги
    подставляются здесь из своей базы. Свой звонок, если он вернулся с
    сервера в старом общем документе, второй раз не показывается.
    """
    import json

    row = await session.get(AppSetting, "hub_calls_cache")
    if row is None or not row.value:
        return []
    кэш = json.loads(row.value)
    клиенты = {c.yclients_id: c for c in (await session.execute(select(Client))).scalars()}
    уже = {(r["yclients_id"], r["at_utc"]) for r in свои}
    пришли: list[tuple[dict, datetime]] = []
    for месяц in кэш.values():
        for з in месяц if isinstance(месяц, list) else []:
            try:
                когда = datetime.fromisoformat(з["at"]).astimezone(MOSCOW)
            except (KeyError, TypeError, ValueError):
                continue
            if (с and когда.date() < с) or (по and когда.date() > по):
                continue
            ключ = (з.get("yclients_id"), когда.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M"))
            if ключ in уже:
                continue
            уже.add(ключ)
            пришли.append((з, когда))
    if not пришли:
        return []
    ids = [клиенты[з["yclients_id"]].id for з, _ in пришли if з.get("yclients_id") in клиенты]
    теги = await tags_by_client(session, ids)
    номера = {з.get("record_id") for з, _ in пришли if з.get("record_id")}
    визиты = {
        yid: (когда, статус)
        for yid, когда, статус in (await session.execute(
            select(Visit.yclients_id, Visit.datetime, Visit.status).where(Visit.yclients_id.in_(номера))
        )).all()
    } if номера else {}
    out = []
    for i, (з, когда) in enumerate(пришли):
        клиент = клиенты.get(з.get("yclients_id"))
        исход = з.get("outcome")
        запись = визиты.get(з.get("record_id"))
        out.append({
            "id": -(i + 1),  # не свой звонок: в своей таблице его нет
            "at": когда.isoformat(),
            "at_utc": когда.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M"),
            "call_date": когда.date().isoformat(),
            "client_id": клиент.id if клиент else None,
            "yclients_id": з.get("yclients_id"),
            "name": клиент.name if клиент else f"Клиент #{з.get('yclients_id')}",
            "phone": клиент.phone if клиент else None,
            "yclients_url": ссылка_yclients(клиент.phone) if клиент else None,
            "outcome": исход,
            "outcome_label": СТАТУСЫ.get(исход, исход),
            "tags": [{"name": т["name"], "color": т.get("color")} for т in теги.get(клиент.id, [])] if клиент else [],
            "next_contact_at": клиент.next_contact_at.isoformat() if клиент and клиент.next_contact_at else None,
            "booking": (з.get("verification") or "pending") if исход == "booked" else None,
            "was_lost": bool(з.get("was_lost")),
            "admin": з.get("admin"),
            "booking_at": _в_москву(запись[0]) if запись else None,
            "booking_visit": запись[1] if запись else None,
        })
    return out


async def call_log(session: AsyncSession, с: date | None, по: date | None) -> dict:
    """Журнал обзвона: каждое нажатие кнопки результата — строка, новые сверху.

    Период включительно с обеих сторон; ``с=None`` — за всё время. Имена и
    телефоны берутся из локальной базы и наружу не уходят.
    """
    условия = []
    if с is not None:
        условия.append(ContactAttempt.created_at >= datetime.combine(с, datetime.min.time(), tzinfo=MOSCOW))
    if по is not None:
        условия.append(ContactAttempt.created_at < datetime.combine(по + timedelta(days=1), datetime.min.time(), tzinfo=MOSCOW))
    строки = (await session.execute(
        select(ContactAttempt, ContactTask, Client)
        .join(ContactTask, ContactTask.id == ContactAttempt.task_id)
        .join(Client, Client.id == ContactTask.client_id)
        .where(*условия)
        .order_by(ContactAttempt.created_at.desc(), ContactAttempt.id.desc())
    )).all()
    теги = await tags_by_client(session, list({c.id for _, _, c in строки}))
    # Дата записи, которую сверка нашла в YCLIENTS: запись лежит у нас же в
    # visits (yclients_id записи = yclients_record_id звонка) — без запросов.
    номера_записей = {п.yclients_record_id for п, _, _ in строки if п.yclients_record_id}
    записи = {
        yid: (когда, статус)
        for yid, когда, статус in (await session.execute(
            select(Visit.yclients_id, Visit.datetime, Visit.status).where(Visit.yclients_id.in_(номера_записей))
        )).all()
    } if номера_записей else {}

    out = []
    for попытка, задача, клиент in строки:
        когда = попытка.created_at
        когда = когда.astimezone(MOSCOW) if когда.tzinfo else когда.replace(tzinfo=MOSCOW)
        out.append({
            "id": попытка.id,
            "at": когда.isoformat(),
            # Ключ сверки со звонками с сервера — ровно как его пишет hub._utc.
            "at_utc": (попытка.created_at.replace(tzinfo=ZoneInfo("UTC")) if попытка.created_at.tzinfo is None
                       else попытка.created_at.astimezone(ZoneInfo("UTC"))).strftime("%Y-%m-%dT%H:%M"),
            "call_date": когда.date().isoformat(),
            "client_id": клиент.id,
            "yclients_id": клиент.yclients_id,
            "name": клиент.name,
            "phone": клиент.phone,
            "yclients_url": ссылка_yclients(клиент.phone),
            "outcome": попытка.outcome,
            "outcome_label": СТАТУСЫ.get(попытка.outcome, попытка.outcome),
            "tags": [{"name": т["name"], "color": т.get("color")} for т in теги.get(клиент.id, [])],
            "next_contact_at": клиент.next_contact_at.isoformat() if клиент.next_contact_at else None,
            # Светофор записи — только у «Записан»: confirmed / not_confirmed / pending.
            "booking": (попытка.verification_status or "pending") if попытка.outcome == "booked" else None,
            "was_lost": bool(попытка.was_lost),
            "admin": попытка.actor_id,
            "booking_at": _в_москву(записи[попытка.yclients_record_id][0])
            if попытка.yclients_record_id in записи else None,
            "booking_visit": записи[попытка.yclients_record_id][1] if попытка.yclients_record_id in записи else None,
        })
    out += await _звонки_других_компьютеров(session, с, по, out)
    out.sort(key=lambda r: r["at"], reverse=True)
    записи = [r for r in out if r["outcome"] == "booked"]
    return {
        "from": с.isoformat() if с else None,
        "to": по.isoformat() if по else None,
        "counters": {
            "calls": len(out),
            "booked": len(записи),
            "returned": sum(1 for r in записи if r["was_lost"]),
        },
        "rows": out,
    }


async def set_do_not_call(session: AsyncSession, client_id: int, value: bool, actor: str | None) -> dict:
    """Пометить «НЕ ЗВОНИТЬ!» или снять пометку. При пометке открытые задачи
    этого клиента убираются из сегодняшней очереди сразу, не дожидаясь пересборки."""
    from sqlalchemy import delete

    client = await session.get(Client, client_id)
    if client is None:
        return {"ok": False, "error": "client not found"}
    client.do_not_call = value
    client.do_not_call_at = datetime.now(MOSCOW) if value else None
    client.do_not_call_by = (actor or "")[:64] or None if value else None
    removed = 0
    if value:
        res = await session.execute(
            delete(ContactTask).where(ContactTask.client_id == client_id, ContactTask.status == "open")
        )
        removed = res.rowcount or 0
    await session.commit()
    return {"ok": True, "client_id": client_id, "do_not_call": value, "tasks_removed": removed}


async def calls_today(session: AsyncSession, admin_staff_id: int | None = None) -> dict:
    """Счётчик звонков за сегодня: всего, записались, без записи, не дозвонились.
    Плюс рекорд — лучший день за 90 дней, чтобы было с чем соревноваться."""
    today = moscow_today()
    start = datetime.combine(today - timedelta(days=90), datetime.min.time(), tzinfo=MOSCOW)
    rows = (await session.execute(
        select(ContactAttempt.outcome, ContactAttempt.created_at, ContactAttempt.admin_staff_id)
        .where(ContactAttempt.created_at >= start)
    )).all()
    def счёт(отбор) -> dict:
        out = {"total": 0, "booked": 0, "no_booking": 0, "no_answer": 0}
        for outcome, when, _ in отбор:
            out["total"] += 1
            if outcome in out:
                out[outcome] += 1
        return out
    по_дням: dict[date, int] = defaultdict(int)
    сегодня, моё = [], []
    for r in rows:
        when = r[1].astimezone(MOSCOW) if r[1].tzinfo else r[1].replace(tzinfo=MOSCOW)
        по_дням[when.date()] += 1
        if when.date() == today:
            сегодня.append(r)
            if admin_staff_id is not None and r[2] == admin_staff_id:
                моё.append(r)
    прошлые = [n for d, n in по_дням.items() if d != today]
    return {"date": today.isoformat(), "salon": счёт(сегодня),
            "mine": счёт(моё) if admin_staff_id is not None else None,
            "record": max(прошлые) if прошлые else 0}


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


СТАТУСЫ = {
    "booked": "Записан",
    "callback": "Перезвонить",
    "no_booking": "Без записи",
    "no_answer": "Не дозвонились",
    "do_not_call": "Не звонить",
}


async def record_outcome(
    session: AsyncSession,
    task_id: int,
    outcome: str,
    channel: str,
    comment: str | None,
    actor_id: str | None,
    admin_staff_id: int | None = None,
    next_contact: date | None = None,
) -> dict:
    """Отметить исход звонка.

    Правила владельца (16.10.2026): «Перезвонить» без даты не принимается, а
    «Не дозвонились» само ставит завтрашний день — иначе клиент потеряется.
    """
    if outcome not in СТАТУСЫ:
        return {"ok": False, "error": f"неизвестный статус: {outcome}"}
    if outcome == "callback" and next_contact is None:
        return {"ok": False, "error": "Для статуса «Перезвонить» нужна дата следующего звонка"}
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
        admin_staff_id=admin_staff_id,
        # «Записан» — не результат, а заявка на проверку в YCLIENTS.
        verification_status="pending" if outcome == "booked" else None,
        # Сегмент после записи меняется, поэтому «был потерян» фиксируем
        # сейчас: по нему считается вкладка «Возвращённые».
        was_lost=task.group_code == "lost",
    )
    session.add(attempt)
    when = datetime.now(MOSCOW)
    # Дату ставим, только если разговор состоялся. «Не дозвонились» — не
    # разговор: клиент должен остаться наверху очереди и ждать повтора.
    client = await session.get(Client, task.client_id)
    if client is not None:
        client.last_call_outcome = outcome
        client.call_status = outcome
        client.last_call_by = actor_id
        if outcome != "no_answer":
            client.last_call_at = when
        if outcome == "no_answer":
            # Не дозвонились — пробуем завтра, иначе клиент утонет в очереди.
            client.next_contact_at = when.date() + timedelta(days=1)
            client.next_contact_note = client.next_contact_note or "не дозвонились"
            client.next_contact_by = actor_id
        elif outcome == "callback":
            client.next_contact_at = next_contact
            client.next_contact_note = (comment or client.next_contact_note or "перезвонить")[:200]
            client.next_contact_by = actor_id
        elif outcome == "do_not_call":
            client.do_not_call = True
            client.do_not_call_at = when
            client.do_not_call_by = actor_id
            client.next_contact_at = None
        else:
            client.next_contact_at = None
            client.next_contact_note = None
    await session.commit()

    # Результат уже сохранён. Журнал пишем после коммита и отдельно: файл на
    # диске — вещь ненадёжная, а звонок терять нельзя.
    await call_journal.append_attempt(session, task_id, attempt, when=when)
    return {"ok": True, "task_id": task_id}


# --------------------------------------------------------------------------- #
# Баланс базы: новые минус потерянные (решение владельца 04.10.2026)
# --------------------------------------------------------------------------- #

PULSE_START_KEY = "pulse_start_date"


def base_flow(
    visits: dict[int, list[date]],
    first_known: dict[int, date | None],
    start: date,
    today: date,
) -> dict:
    """Приток и отток базы по дням с ``start`` по ``today``.

    Новый — первый визит клиента и возвращение после потери (решение владельца:
    вернувшийся считается новым; в ответе они разделены). Потерянный в день D —
    клиент, чей визит был ровно LOST_AFTER_DAYS + 1 дней назад и после него
    не было визита. Пульс дня = новые − потерянные, итог — накопление со start.
    Будущая запись, снимающая «потерянного», задним числом неизвестна и не
    учитывается — как и в backfill_metric_history.
    """
    first: dict[date, int] = defaultdict(int)
    back: dict[date, int] = defaultdict(int)
    lost: dict[date, int] = defaultdict(int)
    for cid, raw in visits.items():
        v = sorted(set(raw))
        if not v:
            continue
        known = first_known.get(cid)
        if known is None or known >= v[0]:  # иначе ранние визиты вне нашей истории
            first[v[0]] += 1
        for a, b in zip(v, v[1:]):
            if (b - a).days > LOST_AFTER_DAYS:
                lost[a + timedelta(days=LOST_AFTER_DAYS + 1)] += 1
                back[b] += 1
        last_lost = v[-1] + timedelta(days=LOST_AFTER_DAYS + 1)
        lost[last_lost] += 1
    days, total, d = [], 0, start
    while d <= today:
        n, r, l = first.get(d, 0), back.get(d, 0), lost.get(d, 0)
        pulse = n + r - l
        total += pulse
        days.append({"date": d.isoformat(), "new": n, "returned": r, "lost": l,
                     "pulse": pulse, "total": total})
        d += timedelta(days=1)
    return {"start": start.isoformat(), "days": days, "total": total,
            "new": sum(x["new"] for x in days), "returned": sum(x["returned"] for x in days),
            "lost": sum(x["lost"] for x in days)}


async def get_pulse_start(session: AsyncSession) -> date | None:
    row = await session.get(AppSetting, PULSE_START_KEY)
    return date.fromisoformat(row.value) if row and row.value else None


async def set_pulse_start(session: AsyncSession, value: date) -> None:
    row = await session.get(AppSetting, PULSE_START_KEY)
    if row is None:
        session.add(AppSetting(key=PULSE_START_KEY, value=value.isoformat()))
    else:
        row.value = value.isoformat()
    await session.commit()


async def build_base_flow(session: AsyncSession) -> dict:
    today = moscow_today()
    start = await get_pulse_start(session)
    if start is None:
        return {"start": None, "days": [], "today": today.isoformat()}
    visits, _ = await _client_visit_summary(session)
    rows = await session.execute(select(Client.id, Client.first_visit_date))
    first_known = {cid: _to_moscow_date(dt) if dt else None for cid, dt in rows}
    out = base_flow(visits, first_known, start, today)
    earliest = min((v[0] for v in visits.values() if v), default=None)
    out["today"] = today.isoformat()
    out["history_from"] = earliest.isoformat() if earliest else None
    out["lost_after_days"] = LOST_AFTER_DAYS
    return out
