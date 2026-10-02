"""Месячный отчёт: мастера, администраторы, проверяемая статистика обзвона.

Принципы (ТЗ «Месячный отчёт»):

* расчёты мастеров переиспользуют формулы ``barber_month`` (выполненный визит,
  сумма услуг, продажи товаров) и ``finance.get_return_rate`` (возвратность);
* нажатие «Записан» не результат: результат — запись, найденная в YCLIENTS
  по ДАТЕ СОЗДАНИЯ, причём одна запись подтверждает только один звонок;
* ошибка YCLIENTS не равна отсутствию записи: статус остаётся ``pending`` или
  ``error``, ``not_confirmed`` ставится лишь после закрытия окна и удачной
  загрузки;
* нет данных — значит «нет данных» (``None``), а не ноль;
* имена полей YCLIENTS для даты создания и автора записи в проекте не
  подтверждены и не угадываются: их называет владелец в настройках отчёта
  после «Проверки полей».

Чистые функции (без сети и базы) вынесены отдельно, чтобы их можно было
проверять тестами A–R из ТЗ.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from zoneinfo import ZoneInfo

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.models import (
    Client,
    ContactAttempt,
    ContactTask,
    MonthlyReportSnapshot,
    ReportSetting,
    SyncRun,
)
from app.services import barber_month as bm
from app.services.cache import cached, invalidate

MOSCOW = ZoneInfo("Europe/Moscow")
DATA_VERSION = 1

# Статусы проверки кнопки «Записан».
PENDING, CONFIRMED, NOT_CONFIRMED, ERROR = "pending", "confirmed", "not_confirmed", "error"
OUTCOME_BOOKED, OUTCOME_NO_BOOKING, OUTCOME_NO_ANSWER = "booked", "no_booking", "no_answer"

# Подписи кнопок — как в интерфейсе обзвона (ClientBasePage.tsx).
BUTTON_LABELS = {
    OUTCOME_BOOKED: "Записан",
    OUTCOME_NO_BOOKING: "Без записи",
    OUTCOME_NO_ANSWER: "Не дозвонились",
}

ДЕФОЛТЫ: dict[str, Any] = {
    "targets": {"extra_services_norm": 35, "sales_ratio_norm_pct": 10},
    "extra_service_ids": [],
    "admins": [],  # [{"staff_id": int, "name": str, "creator_values": [str]}]
    "attribution_window_days": 3,
    "record_created_field": "",
    "record_creator_field": "",
    "horizon_days": 60,
}


# ── Настройки ─────────────────────────────────────────────────────────────


async def load_settings(session: AsyncSession) -> dict[str, Any]:
    rows = (await session.execute(select(ReportSetting))).scalars().all()
    result = {k: (v.copy() if isinstance(v, (dict, list)) else v) for k, v in ДЕФОЛТЫ.items()}
    for row in rows:
        if row.key in result and row.value is not None:
            if isinstance(result[row.key], dict) and isinstance(row.value, dict):
                result[row.key] = {**result[row.key], **row.value}
            else:
                result[row.key] = row.value
    return result


def _clean_settings(patch: dict[str, Any]) -> dict[str, Any]:
    """Проверить присланное. Неизвестные ключи отбрасываются."""
    out: dict[str, Any] = {}
    if "targets" in patch:
        t = patch["targets"] or {}
        norm = int(t.get("extra_services_norm", ДЕФОЛТЫ["targets"]["extra_services_norm"]))
        ratio = float(t.get("sales_ratio_norm_pct", ДЕФОЛТЫ["targets"]["sales_ratio_norm_pct"]))
        if norm < 0 or ratio < 0:
            raise ValueError("Нормативы не могут быть отрицательными")
        out["targets"] = {"extra_services_norm": norm, "sales_ratio_norm_pct": ratio}
    if "extra_service_ids" in patch:
        out["extra_service_ids"] = sorted({int(x) for x in patch["extra_service_ids"] or []})
    if "admins" in patch:
        admins = []
        seen: set[int] = set()
        for a in patch["admins"] or []:
            sid = int(a["staff_id"])
            name = str(a.get("name") or "").strip()
            if not name or sid in seen:
                continue
            seen.add(sid)
            values = [str(v).strip() for v in (a.get("creator_values") or []) if str(v).strip()]
            admins.append({"staff_id": sid, "name": name, "creator_values": values})
        out["admins"] = admins
    if "attribution_window_days" in patch:
        days = int(patch["attribution_window_days"])
        if not 0 <= days <= 60:
            raise ValueError("Окно проверки — от 0 до 60 дней")
        out["attribution_window_days"] = days
    if "horizon_days" in patch:
        days = int(patch["horizon_days"])
        if not 7 <= days <= 365:
            raise ValueError("Горизонт записей — от 7 до 365 дней")
        out["horizon_days"] = days
    for key in ("record_created_field", "record_creator_field"):
        if key in patch:
            value = str(patch[key] or "").strip()
            if value and not all(ch.isalnum() or ch in "_." for ch in value):
                raise ValueError("Имя поля — латинские буквы, цифры, «_» и «.»")
            out[key] = value
    return out


async def save_settings(session: AsyncSession, patch: dict[str, Any]) -> dict[str, Any]:
    clean = _clean_settings(patch)
    for key, value in clean.items():
        row = await session.get(ReportSetting, key)
        if row is None:
            session.add(ReportSetting(key=key, value=value))
        else:
            row.value = value
    await session.commit()
    invalidate("monthly:")
    return await load_settings(session)


# ── Время и арифметика ────────────────────────────────────────────────────


def parse_month(ym: str) -> tuple[datetime, datetime]:
    """«2026-09» → [начало, начало следующего месяца) по Москве."""
    try:
        year, month = (int(x) for x in ym.split("-"))
        start = datetime(year, month, 1, tzinfo=MOSCOW)
    except (ValueError, AttributeError) as exc:
        raise ValueError("Месяц указывается как ГГГГ-ММ") from exc
    end = start.replace(day=calendar.monthrange(year, month)[1]) + timedelta(days=1)
    return start, end.replace(hour=0, minute=0, second=0, microsecond=0)


def month_key(d: datetime | date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def prev_month(ym: str) -> str:
    start, _ = parse_month(ym)
    return month_key(start - timedelta(days=1))


def month_status(ym: str, now: datetime) -> str:
    """preliminary — месяц ещё идёт, final — завершён."""
    _, end = parse_month(ym)
    return "final" if now.astimezone(MOSCOW) >= end else "preliminary"


def delta_pct(current: float | None, previous: float | None) -> float | None:
    """Δ% = (Current − Previous) / Previous × 100. Нет данных или Previous=0 → None."""
    if current is None or previous is None or previous == 0:
        return None
    return round((current - previous) / previous * 100, 1)


def _r(value: Decimal | float | None, places: int = 2) -> float | None:
    if value is None:
        return None
    return float(Decimal(str(value)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))


def _ratio(num: float | Decimal | None, den: float | Decimal | None, mult: int = 1) -> float | None:
    if num is None or den is None or not den:
        return None
    return _r(Decimal(str(num)) / Decimal(str(den)) * mult)


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


# ── Разбор записи YCLIENTS ────────────────────────────────────────────────


def record_id(rec: dict) -> int | None:
    value = rec.get("id")
    return int(value) if isinstance(value, int) or str(value).isdigit() else None


def record_staff_id(rec: dict) -> int:
    staff = rec.get("staff")
    return _int(rec.get("staff_id") or (staff.get("id") if isinstance(staff, dict) else 0))


def record_client_id(rec: dict) -> int | None:
    client = rec.get("client")
    value = client.get("id") if isinstance(client, dict) else rec.get("client_id")
    return _int(value) or None


def record_visit_dt(rec: dict) -> datetime | None:
    raw = rec.get("datetime") or rec.get("date")
    if not raw:
        return None
    try:
        return bm.timestamp(raw)
    except (ValueError, TypeError):
        return None


def _dig(rec: dict, path: str) -> Any:
    value: Any = rec
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def parse_created(value: Any) -> tuple[datetime, bool] | None:
    """Разобрать дату создания. Второй элемент — было ли в значении время."""
    if not value:
        return None
    text = str(value).strip()
    has_time = len(text) > 10 and any(ch in text[10:] for ch in ":")
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    dt = dt.replace(tzinfo=MOSCOW) if dt.tzinfo is None else dt.astimezone(MOSCOW)
    return dt, has_time


def record_created(rec: dict, created_field: str) -> tuple[datetime, bool] | None:
    return parse_created(_dig(rec, created_field)) if created_field else None


def record_creator(rec: dict, creator_field: str) -> str | None:
    value = _dig(rec, creator_field) if creator_field else None
    if isinstance(value, dict):
        value = value.get("id") if value.get("id") is not None else value.get("name")
    return None if value in (None, "") else str(value).strip()


def is_completed(rec: dict, now: datetime) -> bool:
    """Выполненный клиентский визит — условие из barber_month.calculate."""
    if rec.get("deleted") or record_client_id(rec) is None:
        return False
    dt = record_visit_dt(rec)
    return dt is not None and dt <= now and bm.visit_attendance(rec) == 1


def _service_lines(rec: dict) -> list[dict]:
    lines = rec.get("services")
    return [x for x in lines if isinstance(x, dict)] if isinstance(lines, list) else []


def unique_records(records: list[dict]) -> list[dict]:
    seen: set[Any] = set()
    out = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        rid = rec.get("id")
        if rid in seen:
            continue
        seen.add(rid)
        out.append(rec)
    return out


# ── Мастера ───────────────────────────────────────────────────────────────


def parse_hours(schedule: list | None, staff_id: int, start: datetime, end: datetime,
                now: datetime) -> tuple[float | None, str | None]:
    """Часы по графику YCLIENTS за месяц до текущего момента.

    Ожидаемый вид интервала — ``{"from": "10:00", "to": "22:00"}``. Всё
    нераспознанное не превращается в часы: возвращается (None, причина).
    """
    if schedule is None:
        return None, "График YCLIENTS недоступен"
    total = 0.0
    found = False
    for row in schedule:
        if not isinstance(row, dict):
            continue
        if _int(row.get("staff_id") or row.get("staffId")) != staff_id:
            continue
        try:
            day = date.fromisoformat(str(row.get("date", ""))[:10])
        except ValueError:
            continue
        day_start = datetime(day.year, day.month, day.day, tzinfo=MOSCOW)
        if not start <= day_start < end or day_start > now:
            continue
        for slot in row.get("slots") or []:
            try:
                h1, m1 = (int(x) for x in str(slot["from"]).split(":")[:2])
                h2, m2 = (int(x) for x in str(slot["to"]).split(":")[:2])
            except (KeyError, TypeError, ValueError):
                return None, "Формат интервалов графика YCLIENTS не распознан"
            a = day_start + timedelta(hours=h1, minutes=m1)
            b = day_start + timedelta(hours=h2, minutes=m2)
            b = min(b, now)
            if b > a:
                total += (b - a).total_seconds() / 3600
                found = True
    if not found:
        return None, "В графике нет рабочих часов мастера"
    return round(total, 2), None


def master_month(
    records: list[dict],
    products: list[dict] | None,
    schedule: list | None,
    rule: dict,
    start: datetime,
    end: datetime,
    now: datetime,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    """Показатели одного мастера за месяц. Без сети и базы."""
    staff_id = int(rule["staff_id"])
    extra_ids = set(cfg.get("extra_service_ids") or [])
    revenue = Decimal(0)
    visits = 0
    extra_count = 0
    extra_rows: list[dict] = []
    visit_rows: list[dict] = []
    for rec in unique_records(records):
        if record_staff_id(rec) != staff_id or not is_completed(rec, now):
            continue
        dt = record_visit_dt(rec)
        if dt is None or not start <= dt < end:
            continue
        amount = bm.amount(rec)
        revenue += amount
        visits += 1
        visit_rows.append({"record_id": rec.get("id"), "at": dt.isoformat(),
                           "client_id": record_client_id(rec), "amount": _r(amount)})
        for line in _service_lines(rec):
            if _int(line.get("id")) in extra_ids:
                qty = _int(line.get("amount")) or 1
                extra_count += qty
                extra_rows.append({
                    "record_id": rec.get("id"), "at": dt.isoformat(),
                    "client_id": record_client_id(rec),
                    "service": line.get("title") or f"Услуга №{line.get('id')}",
                    "quantity": qty,
                })

    today_iso = now.date().isoformat()
    product_sales: Decimal | None = None
    if products is not None:
        product_sales = Decimal(0)
        for sale in products:
            if _int(sale.get("staff_id")) != staff_id:
                continue
            d = str(sale.get("date") or "")[:10]
            if start.date().isoformat() <= d < end.date().isoformat() and d <= today_iso:
                product_sales += bm.money(sale["amount"])

    hours, hours_note = parse_hours(schedule, staff_id, start, end, now)
    revenue_f = _r(revenue)
    norm_extra = int(cfg["targets"]["extra_services_norm"])
    norm_ratio = float(cfg["targets"]["sales_ratio_norm_pct"])
    configured = bool(extra_ids)
    ratio = _ratio(product_sales, revenue, 100) if revenue > 0 else None
    missing = None
    if product_sales is not None and revenue >= 0:
        missing = _r(max(Decimal(0), revenue * Decimal(str(norm_ratio)) / 100 - product_sales))

    return {
        "staff_id": staff_id,
        "name": rule["name"],
        "revenue": revenue_f,
        "visits": visits,
        "avg_check": _ratio(revenue, visits) if visits else None,
        "extra_services": {
            "configured": configured,
            "count": extra_count if configured else None,
            "norm": norm_extra,
            "pct": _ratio(extra_count, norm_extra, 100) if configured and norm_extra else None,
            "met": (extra_count >= norm_extra) if configured else None,
        },
        "hours": hours,
        "hours_note": hours_note,
        "hour_cost": _ratio(revenue, hours) if hours else None,
        "product_sales": _r(product_sales),
        "sales_ratio_pct": ratio,
        "sales_norm_pct": norm_ratio,
        "sales_met": (ratio >= norm_ratio) if ratio is not None else None,
        "sales_missing": missing,
        "_extra_rows": extra_rows,
        "_visit_rows": visit_rows,
    }


def add_master_deltas(cur: dict, prev: dict | None) -> dict:
    """Δ к прошлому месяцу. Нет прошлого или он нулевой → None."""
    prev = prev or {}
    cur["avg_check_prev"] = prev.get("avg_check")
    cur["avg_check_delta"] = delta_pct(cur["avg_check"], prev.get("avg_check"))
    cur["hour_cost_prev"] = prev.get("hour_cost")
    cur["hour_cost_delta"] = delta_pct(cur["hour_cost"], prev.get("hour_cost"))
    return cur


# ── Администраторы: записи ────────────────────────────────────────────────


def _admin_by_creator(admins: list[dict], creator: str | None) -> dict | None:
    if creator is None:
        return None
    for admin in admins:
        if creator.lower() in {str(v).lower() for v in admin.get("creator_values", [])}:
            return admin
    return None


def admin_records(
    records: list[dict], cfg: dict[str, Any], start: datetime, end: datetime, now: datetime
) -> dict[str, Any]:
    """«Сделано» и «Закрыто» по автору записи.

    Возвращает ``available=False`` с причиной, пока владелец не подтвердил
    поля даты создания и автора: назначать администратора по догадке нельзя.
    """
    created_field, creator_field = cfg["record_created_field"], cfg["record_creator_field"]
    if not created_field or not creator_field:
        missing = []
        if not created_field:
            missing.append("дата создания записи")
        if not creator_field:
            missing.append("автор записи")
        return {"available": False,
                "reason": "Поле YCLIENTS не подтверждено: " + ", ".join(missing)
                + ". Откройте «Настройки → Месячный отчёт → Проверить поля».",
                "by_admin": {}, "unassigned": 0}

    by_admin: dict[int, dict] = {}
    unassigned = 0
    for rec in unique_records(records):
        if rec.get("deleted") or record_client_id(rec) is None:
            continue
        admin = _admin_by_creator(cfg["admins"], record_creator(rec, creator_field))
        created = record_created(rec, created_field)
        visit = record_visit_dt(rec)
        if admin is None:
            unassigned += 1
            continue
        row = by_admin.setdefault(admin["staff_id"], {
            "made": {"count": 0, "sum": Decimal(0)}, "closed": {"count": 0, "sum": Decimal(0)},
            "made_rows": [], "closed_rows": [],
        })
        amount = bm.amount(rec)
        if created is not None and start <= created[0] < end:
            row["made"]["count"] += 1
            row["made"]["sum"] += amount
            row["made_rows"].append({"record_id": rec.get("id"), "created_at": created[0].isoformat(),
                                     "visit_at": visit.isoformat() if visit else None,
                                     "client_id": record_client_id(rec), "amount": _r(amount)})
        if is_completed(rec, now) and visit is not None and start <= visit < end:
            row["closed"]["count"] += 1
            row["closed"]["sum"] += amount
            row["closed_rows"].append({"record_id": rec.get("id"),
                                       "visit_at": visit.isoformat(),
                                       "client_id": record_client_id(rec), "amount": _r(amount)})
    return {"available": True, "reason": None, "by_admin": by_admin, "unassigned": unassigned}


# ── Проверка кнопки «Записан» ─────────────────────────────────────────────


@dataclass
class Att:
    """Нажатие кнопки обзвона в виде, удобном для сверки с YCLIENTS."""

    id: int
    client_yid: int | None
    outcome: str
    clicked_at: datetime
    status: str | None = None
    record_id: int | None = None
    admin_staff_id: int | None = None
    admin_name: str | None = None
    client_name: str = ""


@dataclass
class Decision:
    status: str
    record_id: int | None = None
    note: str = ""


@dataclass
class Match:
    decisions: dict[int, Decision] = field(default_factory=dict)
    # нажата не «Записан», а запись после звонка появилась: {attempt_id: record_id}
    discrepancies: dict[int, int] = field(default_factory=dict)


def _window_end(clicked: datetime, days: int) -> datetime:
    """Конец окна — конец суток последнего дня окна."""
    last = (clicked + timedelta(days=days)).astimezone(MOSCOW)
    return last.replace(hour=23, minute=59, second=59, microsecond=0)


def match_attempts(
    attempts: list[Att],
    records: list[dict],
    cfg: dict[str, Any],
    now: datetime,
    reserved_ids: set[int] | None = None,
) -> Match:
    """Сопоставить звонки с реальными записями по дате создания.

    Правила ТЗ: запись должна быть создана ПОСЛЕ нажатия и в пределах окна;
    одна запись подтверждает один звонок (ближайший по времени); пока окно
    открыто, отсутствие записи — ``pending``, а не ``not_confirmed``.
    Повторяющиеся нажатия на одну и ту же запись не задваиваются.
    """
    created_field = cfg["record_created_field"]
    window = int(cfg["attribution_window_days"])
    result = Match()
    if not created_field:
        for att in attempts:
            if att.outcome == OUTCOME_BOOKED:
                result.decisions[att.id] = Decision(
                    PENDING, None, "Поле даты создания записи в YCLIENTS не подтверждено")
        return result

    by_client: dict[int, list[tuple[datetime, bool, int]]] = {}
    for rec in unique_records(records):
        rid = record_id(rec)
        cid = record_client_id(rec)
        created = record_created(rec, created_field)
        if rec.get("deleted") or rid is None or cid is None or created is None:
            continue
        by_client.setdefault(cid, []).append((created[0], created[1], rid))
    for items in by_client.values():
        items.sort()

    taken: set[int] = set(reserved_ids or set())
    # уже подтверждённые звонки держат свои записи
    for att in attempts:
        if att.status == CONFIRMED and att.record_id:
            taken.add(att.record_id)

    def candidate(att: Att) -> int | None:
        if att.client_yid is None:
            return None
        end = _window_end(att.clicked_at, window)
        for created, has_time, rid in by_client.get(att.client_yid, []):
            if rid in taken:
                continue
            if has_time:
                after = created >= att.clicked_at
                inside = created <= end
            else:
                after = created.date() >= att.clicked_at.astimezone(MOSCOW).date()
                inside = created.date() <= end.date()
            if after and inside:
                return rid
        return None

    ordered = sorted(attempts, key=lambda a: a.clicked_at)
    # 1) «Записан» — первыми, чтобы запись не ушла другому результату
    for att in ordered:
        if att.outcome != OUTCOME_BOOKED:
            continue
        if att.status == CONFIRMED and att.record_id:
            result.decisions[att.id] = Decision(CONFIRMED, att.record_id, "")
            continue
        if att.client_yid is None:
            result.decisions[att.id] = Decision(NOT_CONFIRMED, None, "У клиента нет client_id")
            continue
        rid = candidate(att)
        if rid is not None:
            taken.add(rid)
            result.decisions[att.id] = Decision(CONFIRMED, rid, "Запись найдена в YCLIENTS")
        elif _window_end(att.clicked_at, window) > now:
            result.decisions[att.id] = Decision(
                PENDING, None,
                f"Окно проверки открыто до {_window_end(att.clicked_at, window):%d.%m.%Y}")
        else:
            result.decisions[att.id] = Decision(
                NOT_CONFIRMED, None,
                f"За {window} дн. после звонка новой записи клиента в YCLIENTS нет")
    # 2) другая кнопка, но запись появилась
    for att in ordered:
        if att.outcome == OUTCOME_BOOKED:
            continue
        rid = candidate(att)
        if rid is not None:
            taken.add(rid)
            result.discrepancies[att.id] = rid
    return result


# ── Загрузка из YCLIENTS ──────────────────────────────────────────────────


@dataclass
class Source:
    records: list[dict]
    products: dict[str, list[dict] | None]
    schedule: dict[str, list | None]
    warnings: list[str]
    loaded_at: datetime


def _months_between(first: datetime, last: datetime) -> list[str]:
    out, cur = [], first.replace(day=1)
    while cur <= last:
        out.append(month_key(cur))
        cur = (cur + timedelta(days=32)).replace(day=1)
    return out


async def load_source(first: datetime, last: datetime, months: list[str], horizon_days: int) -> Source:
    """Записи за диапазон и продажи/график по месяцам. Один общий кэш на 5 минут.

    Записи берутся по дате визита от ``first`` до ``last + horizon``: запись,
    созданная в месяце, может быть на визит позже его конца.
    """
    from app.api.yclients import YClientsClient

    stop = last + timedelta(days=horizon_days)
    key = f"monthly:{settings.yclients_company_id}:{first.date()}:{stop.date()}:{','.join(months)}"

    async def load() -> Source:
        warnings: list[str] = []
        async with YClientsClient() as client:
            records = await bm.pages(client, f"/records/{client.company_id}",
                                     first.date().isoformat(), stop.date().isoformat())
            products: dict[str, list[dict] | None] = {}
            schedule: dict[str, list | None] = {}
            for ym in months:
                m_start, m_end = parse_month(ym)
                a, b = m_start.date().isoformat(), (m_end - timedelta(days=1)).date().isoformat()
                try:
                    products[ym] = await bm.load_products(client, a, b)
                except Exception as exc:
                    logger.warning(f"месячный отчёт: продажи {ym} недоступны: {exc}")
                    products[ym] = None
                    warnings.append(f"Продажи товаров за {ym} недоступны: данные неполные.")
                try:
                    raw = await client._get(f"/company/{client.company_id}/staff/schedule",
                                            {"start_date": a, "end_date": b})
                    data = raw.get("data") if isinstance(raw, dict) else None
                    if not isinstance(data, list):
                        raise ValueError("Invalid schedule")
                    schedule[ym] = data
                except Exception as exc:
                    logger.warning(f"месячный отчёт: график {ym} недоступен: {exc}")
                    schedule[ym] = None
                    warnings.append(f"График YCLIENTS за {ym} недоступен: стоимость часа не рассчитана.")
        return Source(records, products, schedule, warnings, datetime.now(MOSCOW))

    return await cached(key, load, ttl=300)


# ── Обзвон: чтение и проверка ─────────────────────────────────────────────


async def read_attempts(session: AsyncSession, start: datetime | None = None,
                        end: datetime | None = None,
                        only_outcomes: set[str] | None = None) -> list[Att]:
    query = (
        select(ContactAttempt, Client.yclients_id, Client.name)
        .join(ContactTask, ContactAttempt.task_id == ContactTask.id)
        .join(Client, ContactTask.client_id == Client.id)
        .order_by(ContactAttempt.created_at)
    )
    if start is not None:
        query = query.where(ContactAttempt.created_at >= start)
    if end is not None:
        query = query.where(ContactAttempt.created_at < end)
    out = []
    for attempt, yid, name in (await session.execute(query)).all():
        if only_outcomes and attempt.outcome not in only_outcomes:
            continue
        clicked = attempt.created_at
        clicked = clicked.replace(tzinfo=MOSCOW) if clicked.tzinfo is None else clicked.astimezone(MOSCOW)
        out.append(Att(
            id=attempt.id, client_yid=int(yid) if yid else None, outcome=attempt.outcome,
            clicked_at=clicked, status=attempt.verification_status,
            record_id=attempt.yclients_record_id, admin_staff_id=attempt.admin_staff_id,
            admin_name=attempt.actor_id, client_name=name or "",
        ))
    return out


async def verify_pending(session: AsyncSession, now: datetime | None = None,
                         recheck_not_confirmed: bool = False) -> dict[str, Any]:
    """Проверить нажатия «Записан» в YCLIENTS и записать результат в базу.

    Повторно проверяются ``pending`` и ``error``. Ошибка загрузки оставляет
    звонок в ``error``: не «нет записи», а «не смогли проверить».
    """
    now = (now or datetime.now(MOSCOW)).astimezone(MOSCOW)
    cfg = await load_settings(session)
    attempts = await read_attempts(session)
    todo_statuses = {None, PENDING, ERROR} | ({NOT_CONFIRMED} if recheck_not_confirmed else set())
    booked = [a for a in attempts if a.outcome == OUTCOME_BOOKED and a.status in todo_statuses]
    summary = {"checked": len(booked), "confirmed": 0, "not_confirmed": 0, "pending": 0,
               "error": 0, "warning": None}
    if not booked:
        return summary

    if not cfg["record_created_field"]:
        summary["warning"] = "Поле даты создания записи не подтверждено: проверка невозможна"
        summary["pending"] = len(booked)
        return summary

    first = min(a.clicked_at for a in booked).replace(hour=0, minute=0, second=0, microsecond=0)
    last = now
    try:
        source = await load_source(first, last, [month_key(first)], int(cfg["horizon_days"]))
    except Exception as exc:
        logger.warning(f"проверка обзвона: YCLIENTS недоступен: {exc}")
        for att in booked:
            row = await session.get(ContactAttempt, att.id)
            if row.verification_status != CONFIRMED:
                row.verification_status = ERROR
                row.verification_checked_at = now
                row.verification_note = "YCLIENTS недоступен: проверка не выполнена"
        await session.commit()
        summary["error"] = len(booked)
        summary["warning"] = "YCLIENTS недоступен: звонки оставлены в статусе «ошибка проверки»"
        return summary

    match = match_attempts(attempts, source.records, cfg, now)
    for att in booked:
        decision = match.decisions.get(att.id)
        if decision is None:
            continue
        row = await session.get(ContactAttempt, att.id)
        row.verification_status = decision.status
        row.yclients_record_id = decision.record_id
        row.verification_note = decision.note
        row.verification_checked_at = now
        if decision.status == CONFIRMED and row.verified_at is None:
            row.verified_at = now
        summary[decision.status] += 1
    await session.commit()
    return summary


# ── Сборка отчёта ─────────────────────────────────────────────────────────


def _counts(attempts: list[Att], match: Match) -> dict[str, Any]:
    total = len(attempts)
    booked = [a for a in attempts if a.outcome == OUTCOME_BOOKED]
    # статус берём из свежей сверки, а не из базы: отчёт не должен отставать
    def st(a: Att) -> str:
        d = match.decisions.get(a.id)
        return d.status if d else (a.status or PENDING)
    confirmed = sum(1 for a in booked if st(a) == CONFIRMED)
    not_confirmed = sum(1 for a in booked if st(a) == NOT_CONFIRMED)
    pending = sum(1 for a in booked if st(a) == PENDING)
    error = sum(1 for a in booked if st(a) == ERROR)
    no_booking = sum(1 for a in attempts if a.outcome == OUTCOME_NO_BOOKING)
    no_answer = sum(1 for a in attempts if a.outcome == OUTCOME_NO_ANSWER)
    reached = len(booked) + no_booking
    discrepancies = sum(1 for a in attempts if a.id in match.discrepancies)
    return {
        "total": total, "booked_clicks": len(booked), "confirmed": confirmed,
        "not_confirmed": not_confirmed, "pending": pending, "error": error,
        "no_booking": no_booking, "no_answer": no_answer, "discrepancies": discrepancies,
        "button_accuracy_pct": _ratio(confirmed, len(booked), 100) if booked else None,
        "conv_contacts_pct": _ratio(confirmed, reached, 100) if reached else None,
        "conv_all_pct": _ratio(confirmed, total, 100) if total else None,
    }


def integrity_checks(masters: list[dict], admins: list[dict]) -> list[dict]:
    checks = []
    for m in masters:
        checks.append({"name": f"{m['name']}: услуги ≥ 0", "ok": (m["revenue"] or 0) >= 0})
        checks.append({"name": f"{m['name']}: визиты ≥ 0", "ok": m["visits"] >= 0})
        if m["product_sales"] is not None:
            checks.append({"name": f"{m['name']}: продажи товаров ≥ 0", "ok": m["product_sales"] >= 0})
    for a in admins:
        c = a["calls"]
        checks.append({"name": f"{a['name']}: подтверждено ≤ нажатий «Записан»",
                       "ok": c["confirmed"] <= c["booked_clicks"]})
    return checks


async def _return_rates(session: AsyncSession, as_of: datetime | None) -> tuple[dict[int, float | None], str | None]:
    from app.services import finance

    try:
        data = await finance.get_return_rate(session, as_of=as_of)
    except Exception as exc:  # возвратность — справочный показатель, отчёт не роняем
        logger.warning(f"месячный отчёт: возвратность не рассчитана: {exc}")
        return {}, "Возвратность не рассчитана"
    return {int(m["staff_id"]): m["return_rate_pct"] for m in data["masters"]}, None


async def _last_sync(session: AsyncSession) -> str | None:
    row = (await session.execute(
        select(SyncRun).where(SyncRun.ok.is_(True)).order_by(SyncRun.id.desc()).limit(1)
    )).scalars().first()
    if row is None:
        return None
    finished = row.finished_at
    finished = finished.replace(tzinfo=MOSCOW) if finished.tzinfo is None else finished.astimezone(MOSCOW)
    return finished.isoformat()


def _snapshot_to_payload(snap: MonthlyReportSnapshot) -> dict[str, Any]:
    return {
        "month": snap.report_month, "state": "final", "label": "Итоговый",
        "generated_at": snap.generated_at.isoformat(),
        "finalized_at": snap.finalized_at.isoformat() if snap.finalized_at else None,
        "masters": snap.master_metrics, "admins": snap.admin_metrics,
        "targets": snap.targets, "data_version": snap.data_version,
        "warnings": snap.warnings, "from_snapshot": True,
    }


def _public(rows: list[dict]) -> list[dict]:
    return [{k: v for k, v in row.items() if not k.startswith("_")} for row in rows]


async def compute(session: AsyncSession, ym: str, now: datetime | None = None) -> dict[str, Any]:
    """Посчитать отчёт заново по данным YCLIENTS. Возвращает payload и детали."""
    now = (now or datetime.now(MOSCOW)).astimezone(MOSCOW)
    start, end = parse_month(ym)
    cfg = await load_settings(session)
    warnings: list[str] = []
    prev_ym = prev_month(ym)
    prev_start, prev_end = parse_month(prev_ym)

    prev_snap = await session.get(MonthlyReportSnapshot, prev_ym)
    need_prev_live = prev_snap is None
    first = prev_start if need_prev_live else start
    months = [prev_ym, ym] if need_prev_live else [ym]
    source = await load_source(first, end - timedelta(days=1), months, int(cfg["horizon_days"]))
    warnings.extend(source.warnings)

    rules = settings.barber_payroll_rules
    returns, ret_warn = await _return_rates(session, end if month_status(ym, now) == "final" else None)
    if ret_warn:
        warnings.append(ret_warn)

    masters, master_details = [], {}
    prev_by_staff = {}
    if prev_snap is not None:
        prev_by_staff = {int(m["staff_id"]): m for m in prev_snap.master_metrics}
    for rule in rules:
        cur = master_month(source.records, source.products.get(ym), source.schedule.get(ym),
                           rule, start, end, now, cfg)
        if need_prev_live:
            prev = master_month(source.records, source.products.get(prev_ym),
                                source.schedule.get(prev_ym), rule, prev_start, prev_end, now, cfg)
        else:
            prev = prev_by_staff.get(int(rule["staff_id"]))
        add_master_deltas(cur, prev)
        cur["return_rate_pct"] = returns.get(int(rule["staff_id"]))
        master_details[int(rule["staff_id"])] = {"extra": cur["_extra_rows"], "visits": cur["_visit_rows"]}
        masters.append(cur)
    if not cfg["extra_service_ids"]:
        warnings.append("Допуслуги не настроены: показатель «Доп. услуги» не рассчитан.")
    if any(m["hours_note"] for m in masters):
        notes = sorted({m["hours_note"] for m in masters if m["hours_note"]})
        warnings.append("Стоимость часа: " + "; ".join(notes))

    # администраторы
    rec_now = admin_records(source.records, cfg, start, end, now)
    rec_prev = (admin_records(source.records, cfg, prev_start, prev_end, now)
                if need_prev_live else None)
    prev_admin_snap = {}
    if prev_snap is not None:
        prev_admin_snap = {a["key"]: a for a in prev_snap.admin_metrics}
    if not rec_now["available"]:
        warnings.append(rec_now["reason"])

    attempts = await read_attempts(session, start, end)
    all_attempts = await read_attempts(session)
    match = match_attempts(all_attempts, source.records, cfg, now)
    month_ids = {a.id for a in attempts}
    match_month = Match({k: v for k, v in match.decisions.items() if k in month_ids},
                        {k: v for k, v in match.discrepancies.items() if k in month_ids})

    groups: dict[str, dict] = {}
    for admin in cfg["admins"]:
        groups[f"a{admin['staff_id']}"] = {"key": f"a{admin['staff_id']}", "staff_id": admin["staff_id"],
                                           "name": admin["name"], "attempts": []}
    groups["none"] = {"key": "none", "staff_id": None, "name": "Администратор не указан", "attempts": []}
    for att in attempts:
        key = f"a{att.admin_staff_id}" if att.admin_staff_id else "none"
        if key not in groups:
            groups[key] = {"key": key, "staff_id": att.admin_staff_id,
                           "name": att.admin_name or f"Сотрудник №{att.admin_staff_id}", "attempts": []}
        groups[key]["attempts"].append(att)

    admins, admin_details = [], {}
    for key, g in groups.items():
        calls = _counts(g["attempts"], match_month)
        if g["staff_id"] is None and calls["total"] == 0:
            continue
        rec = rec_now["by_admin"].get(g["staff_id"]) if g["staff_id"] is not None else None
        made = closed = None
        avg = avg_prev = None
        if rec_now["available"] and g["staff_id"] is not None:
            blank = {"made": {"count": 0, "sum": Decimal(0)}, "closed": {"count": 0, "sum": Decimal(0)}}
            r = rec or blank
            made = {"count": r["made"]["count"], "sum": _r(r["made"]["sum"])}
            closed = {"count": r["closed"]["count"], "sum": _r(r["closed"]["sum"])}
            avg = _ratio(r["closed"]["sum"], r["closed"]["count"]) if r["closed"]["count"] else None
            if rec_prev is not None and rec_prev["available"]:
                rp = rec_prev["by_admin"].get(g["staff_id"])
                avg_prev = (_ratio(rp["closed"]["sum"], rp["closed"]["count"])
                            if rp and rp["closed"]["count"] else None)
            elif key in prev_admin_snap:
                avg_prev = prev_admin_snap[key].get("avg_check")
        admins.append({
            "key": key, "staff_id": g["staff_id"], "name": g["name"], "made": made, "closed": closed,
            "avg_check": avg, "avg_check_prev": avg_prev, "avg_check_delta": delta_pct(avg, avg_prev),
            "calls": calls,
        })
        rows = {"not_confirmed": [], "pending": [], "confirmed": [], "discrepancy": [], "error": [],
                "made": (rec or {}).get("made_rows", []), "closed": (rec or {}).get("closed_rows", [])}
        for att in g["attempts"]:
            d = match_month.decisions.get(att.id)
            item = {"attempt_id": att.id, "client_id": att.client_yid, "client": att.client_name,
                    "admin": g["name"], "at": att.clicked_at.isoformat(),
                    "button": BUTTON_LABELS.get(att.outcome, att.outcome),
                    "record_id": (d.record_id if d else att.record_id),
                    "record_found": bool(d and d.record_id), "reason": d.note if d else ""}
            if att.outcome == OUTCOME_BOOKED and d is not None:
                rows[d.status].append(item)
            elif att.id in match_month.discrepancies:
                item["record_id"] = match_month.discrepancies[att.id]
                item["record_found"] = True
                item["reason"] = "Есть запись YCLIENTS, но результат звонка ≠ «Записан»"
                rows["discrepancy"].append(item)
        admin_details[key] = rows

    warnings_calls = []
    if any(a["calls"]["pending"] for a in admins):
        warnings_calls.append("Есть звонки в ожидании проверки: окно атрибуции ещё не закрыто.")
    if any(a["calls"]["error"] for a in admins):
        warnings_calls.append("Часть звонков не удалось проверить: YCLIENTS был недоступен.")
    if not cfg["record_created_field"] and any(a["calls"]["booked_clicks"] for a in admins):
        warnings_calls.append("Проверка звонков невозможна: поле даты создания записи не подтверждено.")
    warnings.extend(w for w in warnings_calls if w not in warnings)
    if not cfg["admins"]:
        warnings.append("Список администраторов не задан в настройках отчёта.")

    checks = integrity_checks(masters, admins)
    for c in checks:
        if not c["ok"]:
            warnings.append(f"Проверка целостности не пройдена: {c['name']}")

    state = month_status(ym, now)
    payload = {
        "month": ym, "state": state, "label": "Итоговый" if state == "final" else "Предварительный",
        "generated_at": source.loaded_at.isoformat(), "finalized_at": None,
        "last_sync_at": await _last_sync(session),
        "masters": _public(masters), "admins": admins,
        "targets": cfg["targets"], "data_version": DATA_VERSION,
        "warnings": warnings, "checks": checks, "from_snapshot": False,
        "admin_records_available": rec_now["available"],
        "admin_records_unassigned": rec_now["unassigned"],
    }
    details = {"masters": master_details, "admins": admin_details}
    return {"payload": payload, "details": details, "cfg": cfg}


# предупреждения, при которых итог сохранять нельзя: данные неполны
_INCOMPLETE_MARKERS = ("недоступ", "не подтверждено", "не рассчитан", "целостности", "ожидан", "не удалось")


async def build_report(session: AsyncSession, ym: str, *, refresh: bool = False,
                       now: datetime | None = None) -> dict[str, Any]:
    now = (now or datetime.now(MOSCOW)).astimezone(MOSCOW)
    start, end = parse_month(ym)
    if start > now:
        raise ValueError("Этот месяц ещё не наступил")
    state = month_status(ym, now)

    if state == "final" and not refresh:
        snap = await session.get(MonthlyReportSnapshot, ym)
        if snap is not None:
            payload = _snapshot_to_payload(snap)
            payload["last_sync_at"] = await _last_sync(session)
            return payload

    if refresh:
        invalidate("monthly:")
        await verify_pending(session, now, recheck_not_confirmed=(state == "final"))
    elif state == "final":
        # итоговое формирование: сначала повторная проверка ожидающих
        await verify_pending(session, now)

    result = await compute(session, ym, now)
    payload = result["payload"]

    if state == "final":
        incomplete = [w for w in payload["warnings"]
                      if any(mark in w.lower() for mark in _INCOMPLETE_MARKERS)]
        if not incomplete:
            snap = await session.get(MonthlyReportSnapshot, ym)
            stamp = datetime.now(MOSCOW)
            values = dict(
                generated_at=stamp, finalized_at=stamp,
                master_metrics=payload["masters"], admin_metrics=payload["admins"],
                targets=payload["targets"], data_version=DATA_VERSION, warnings=payload["warnings"],
            )
            if snap is None:
                session.add(MonthlyReportSnapshot(report_month=ym, **values))
            else:
                for k, v in values.items():
                    setattr(snap, k, v)
            await session.commit()
            payload["finalized_at"] = stamp.isoformat()
            payload["snapshot_saved"] = True
        else:
            payload["snapshot_saved"] = False
            payload["warnings"].append(
                "Итог не сохранён: данные неполные. После устранения нажмите «Обновить данные».")
    return payload


async def drilldown(session: AsyncSession, ym: str, kind: str, key: str | None,
                    now: datetime | None = None) -> dict[str, Any]:
    """Строки, из которых сложен показатель. Всегда считается по живым данным."""
    result = await compute(session, ym, now)
    details = result["details"]
    if kind in ("extra_services", "visits"):
        rows = details["masters"].get(_int(key), {}).get("extra" if kind == "extra_services" else "visits", [])
    elif kind in ("not_confirmed", "pending", "confirmed", "discrepancy", "error", "made", "closed"):
        rows = details["admins"].get(key or "", {}).get(kind, [])
    else:
        raise ValueError("Неизвестный вид детализации")
    return {"month": ym, "kind": kind, "key": key, "count": len(rows), "rows": rows}


# ── Проверка полей записи YCLIENTS ────────────────────────────────────────

_ЛИЧНОЕ = {"name", "phone", "email", "comment", "client_comment", "surname", "patronymic",
           "full_name", "display_name", "text", "notes", "title"}


def _mask(key: str, value: Any) -> Any:
    if key.lower() in _ЛИЧНОЕ:
        return "***" if value else None
    return value


def describe_record_fields(records: list[dict], limit: int = 50) -> dict[str, Any]:
    """Какие ключи реально приходят в записи. Личные данные скрываются."""
    sample = [r for r in records if isinstance(r, dict)][:limit]
    keys: dict[str, dict[str, Any]] = {}
    for rec in sample:
        for k, v in rec.items():
            info = keys.setdefault(k, {"type": type(v).__name__, "example": None, "filled": 0})
            if v not in (None, "", [], {}):
                info["filled"] += 1
                if info["example"] is None:
                    info["example"] = (f"<{type(v).__name__}: {len(v)}>" if isinstance(v, (list, dict))
                                       else _mask(k, v))
    date_like = [k for k, i in keys.items()
                 if isinstance(i["example"], str) and parse_created(i["example"]) is not None]
    who_like = [k for k in keys
                if any(w in k.lower() for w in ("user", "creator", "author", "admin", "created_by"))]
    # Кто на самом деле создаёт записи: значение поля автора → сколько записей и пример.
    authors: dict[str, list[dict[str, Any]]] = {}
    for field in who_like:
        groups: dict[str, dict[str, Any]] = {}
        for rec in sample:
            v = record_creator(rec, field)
            if v is None:
                continue
            g = groups.setdefault(v, {"value": v, "count": 0, "via_api": 0, "last_created": None})
            g["count"] += 1
            g["via_api"] += 1 if rec.get("api_id") else 0
            created = rec.get("create_date")
            if isinstance(created, str) and (g["last_created"] is None or created > g["last_created"]):
                g["last_created"] = created
        authors[field] = sorted(groups.values(), key=lambda g: -g["count"])
    return {"records_checked": len(sample), "keys": keys,
            "date_candidates": date_like, "creator_candidates": who_like, "authors": authors}


async def probe_fields() -> dict[str, Any]:
    from app.api.yclients import YClientsClient

    today = datetime.now(MOSCOW).date()
    async with YClientsClient() as client:
        rows = await client.get_all_records(
            (today - timedelta(days=7)).isoformat(), (today + timedelta(days=7)).isoformat())
    return describe_record_fields(rows)


async def today_authors(created_field: str = "create_date", creator_field: str = "created_user_id") -> dict[str, Any]:
    """Кто сегодня создавал записи вручную (без сайта/API): ID автора, число записей, время."""
    from app.api.yclients import YClientsClient

    today = datetime.now(MOSCOW).date()
    horizon = 90  # ponytail: запись, созданная сегодня, может быть на любую дату вперёд; дальше 90 дней не ищем
    async with YClientsClient() as client:
        rows = await client.get_all_records(today.isoformat(), (today + timedelta(days=horizon)).isoformat())
    groups: dict[str, dict[str, Any]] = {}
    via_api = 0
    for rec in unique_records(rows):
        created = record_created(rec, created_field)
        if created is None or created[0].date() != today:
            continue
        if rec.get("api_id"):
            via_api += 1
            continue
        who = record_creator(rec, creator_field) or "?"
        g = groups.setdefault(who, {"value": who, "count": 0, "times": []})
        g["count"] += 1
        g["times"].append(created[0].strftime("%H:%M"))
    authors = [dict(g, times=sorted(g["times"])) for g in sorted(groups.values(), key=lambda g: -g["count"])]
    return {"date": today.isoformat(), "authors": authors, "via_api": via_api}
