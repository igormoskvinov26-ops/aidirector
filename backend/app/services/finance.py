"""Financial analysis: marginability, break-even, daily/monthly metrics."""

import calendar
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.models import PlanTarget, Sale, Visit


WORKING_HOURS = range(10, 22)
DB_HOUR_SHIFT = 1
FIXED_DAILY_COST = Decimal("11000.00")
VARIABLE_COST_PCT = Decimal("0.035")
MASTER_COMMISSION_PCT = Decimal("0.40")
MASTER_MIN_SALARY = Decimal("4000.00")
DEFAULT_MASTERS = 2

COMPLETED_STATUSES = {"completed"}


def _compute_margin(revenue: Decimal, num_masters: int) -> dict:
    actual_masters = max(num_masters, 1)
    if revenue <= 0:
        return {
            "margin_rub": Decimal("0"),
            "margin_pct": Decimal("0"),
            "break_even": _break_even_revenue(num_masters),
            "costs": {
                "fixed": FIXED_DAILY_COST,
                "variable": Decimal("0"),
                "master_commission": Decimal("0"),
                "total": FIXED_DAILY_COST,
            },
        }

    variable_cost = revenue * VARIABLE_COST_PCT

    revenue_per_master = revenue / actual_masters
    master_commission_per = max(MASTER_MIN_SALARY, revenue_per_master * MASTER_COMMISSION_PCT)
    master_commission = master_commission_per * actual_masters

    total_costs = FIXED_DAILY_COST + variable_cost + master_commission
    margin_rub = revenue - total_costs
    margin_pct = (margin_rub / revenue * 100).quantize(Decimal("0.1"))

    return {
        "margin_rub": margin_rub,
        "margin_pct": margin_pct,
        "break_even": _break_even_revenue(num_masters),
        "costs": {
            "fixed": FIXED_DAILY_COST,
            "variable": variable_cost,
            "master_commission": master_commission,
            "total": total_costs,
        },
    }


def _break_even_revenue(num_masters: int) -> Decimal:
    if num_masters <= 0:
        num_masters = 1

    denom_high = Decimal("1") - VARIABLE_COST_PCT - MASTER_COMMISSION_PCT
    rev_high = (FIXED_DAILY_COST / denom_high).quantize(Decimal("0.01"))
    threshold = Decimal(10000 * num_masters)

    if rev_high >= threshold:
        return rev_high

    min_total = MASTER_MIN_SALARY * num_masters
    denom_low = Decimal("1") - VARIABLE_COST_PCT
    rev_low = ((FIXED_DAILY_COST + min_total) / denom_low).quantize(Decimal("0.01"))
    return rev_low


DAILY_BREAK_EVEN = _break_even_revenue(DEFAULT_MASTERS)


async def get_daily_finance(
    session: AsyncSession,
    date_from: date,
    date_to: date,
) -> list[dict]:
    day_label = func.date(Visit.datetime)

    rows = await session.execute(
        select(
            day_label.label("day"),
            func.sum(Visit.total_amount).label("revenue"),
            func.sum(
                case((Visit.status.in_(COMPLETED_STATUSES), Visit.total_amount), else_=None)
            ).label("completed_amount"),
            func.sum(
                case((Visit.status.not_in(COMPLETED_STATUSES), Visit.total_amount), else_=None)
            ).label("scheduled_amount"),
            func.count(Visit.id).label("total_visits"),
            func.sum(
                case((Visit.status.in_(COMPLETED_STATUSES), 1), else_=0)
            ).label("completed_visits"),
            func.count(func.distinct(Visit.employee_id)).label("masters_count"),
        )
        .where(
            day_label >= date_from,
            day_label <= date_to,
        )
        .group_by(day_label)
        .order_by(day_label)
    )

    sale_day_label = func.date(Sale.datetime)
    sale_rows = await session.execute(
        select(
            sale_day_label.label("day"),
            func.sum(Sale.total_amount).label("product_sales"),
        )
        .where(
            sale_day_label >= date_from,
            sale_day_label <= date_to,
        )
        .group_by(sale_day_label)
    )
    sales_by_day: dict[str, Decimal] = {}
    for row in sale_rows:
        sales_by_day[str(row.day)] = Decimal(str(row.product_sales or 0))

    result = []
    for row in rows:
        day_str = str(row.day)
        revenue = Decimal(str(row.revenue or 0))
        completed = Decimal(str(row.completed_amount or 0))
        scheduled = Decimal(str(row.scheduled_amount or 0))
        num_masters = int(row.masters_count or 0)
        margin = _compute_margin(completed, num_masters)

        result.append({
            "date": day_str,
            "revenue": float(revenue),
            "completed": float(completed),
            "scheduled": float(scheduled),
            "product_sales": float(sales_by_day.get(day_str, Decimal("0"))),
            "total_visits": row.total_visits or 0,
            "completed_visits": row.completed_visits or 0,
            "masters_count": num_masters,
            "margin_rub": float(margin["margin_rub"]),
            "margin_pct": float(margin["margin_pct"]),
            "break_even": float(DAILY_BREAK_EVEN),
            "costs": {k: float(v) for k, v in margin["costs"].items()},
        })

    result_by_date = {r["date"]: r for r in result}
    filled = []
    current = date_from
    while current <= date_to:
        day_str = current.isoformat()
        if day_str in result_by_date:
            filled.append(result_by_date[day_str])
        else:
            filled.append({
                "date": day_str,
                "revenue": 0,
                "completed": 0,
                "scheduled": 0,
                "product_sales": float(sales_by_day.get(day_str, Decimal("0"))),
                "total_visits": 0,
                "completed_visits": 0,
                "masters_count": 0,
                "margin_rub": 0,
                "margin_pct": 0,
                "break_even": float(DAILY_BREAK_EVEN),
                "costs": {"fixed": 0, "variable": 0, "master_commission": 0, "total": 0},
            })
        current += timedelta(days=1)

    return filled


async def get_monthly_finance(
    session: AsyncSession,
    year: int = 2026,
) -> list[dict]:
    period_label = func.to_char(Visit.datetime, "YYYY-MM")

    rows = await session.execute(
        select(
            period_label.label("month"),
            func.sum(Visit.total_amount).label("revenue"),
            func.count(Visit.id).label("total_visits"),
            func.sum(
                case((Visit.status.in_(COMPLETED_STATUSES), 1), else_=0)
            ).label("completed"),
        )
        .where(
            func.extract("year", Visit.datetime) == year,
        )
        .group_by(period_label)
        .order_by(period_label)
    )

    sale_month_label = func.to_char(Sale.datetime, "YYYY-MM")
    sale_rows = await session.execute(
        select(
            sale_month_label.label("month"),
            func.sum(Sale.total_amount).label("product_sales"),
        )
        .where(
            func.extract("year", Sale.datetime) == year,
        )
        .group_by(sale_month_label)
    )

    sales_by_month: dict[str, Decimal] = {}
    for row in sale_rows:
        sales_by_month[str(row.month)] = Decimal(str(row.product_sales or 0))

    result = []
    for row in rows:
        month_str = str(row.month)
        revenue = Decimal(str(row.revenue or 0))
        year_part, month_part = month_str.split("-")
        days_in_month = _days_in_month(int(year_part), int(month_part))
        monthly_fixed = FIXED_DAILY_COST * days_in_month

        total_visits = row.total_visits or 0
        completed = row.completed or 0

        variable_cost = revenue * VARIABLE_COST_PCT
        master_commission = _estimate_monthly_commission(revenue)
        total_costs = monthly_fixed + variable_cost + master_commission
        margin_rub = revenue - total_costs
        margin_pct = (margin_rub / revenue * 100).quantize(Decimal("0.1")) if revenue > 0 else Decimal("0")

        break_even_monthly = (FIXED_DAILY_COST * days_in_month) / (
            Decimal("1") - VARIABLE_COST_PCT - MASTER_COMMISSION_PCT
        )

        result.append({
            "month": month_str,
            "days_in_month": days_in_month,
            "revenue": revenue,
            "total_visits": total_visits,
            "completed": completed,
            "product_sales": float(sales_by_month.get(month_str, Decimal("0"))),
            "margin_rub": margin_rub,
            "margin_pct": float(margin_pct),
            "break_even": break_even_monthly.quantize(Decimal("0.01")),
            "costs": {
                "fixed": monthly_fixed,
                "variable": variable_cost,
                "master_commission": master_commission,
                "total": total_costs,
            },
        })

    return result


async def get_current_month_plan(session: AsyncSession) -> dict:
    today = date.today()
    period = today.strftime("%Y-%m")

    row = await session.scalar(
        select(PlanTarget).where(PlanTarget.period == period)
    )

    if row:
        return {
            "period": row.period,
            "revenue_target": float(row.revenue_target),
            "margin_target_pct": float(row.margin_target_pct),
        }

    return {
        "period": period,
        "revenue_target": 0,
        "margin_target_pct": 30.0,
    }


async def set_monthly_plan(
    session: AsyncSession,
    period: str,
    revenue_target: Decimal,
    margin_target_pct: float = 30.0,
) -> dict:
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    stmt = pg_insert(PlanTarget).values(
        period=period,
        revenue_target=revenue_target,
        margin_target_pct=margin_target_pct,
    ).on_conflict_do_update(
        index_elements=["period"],
        set_={
            "revenue_target": revenue_target,
            "margin_target_pct": margin_target_pct,
            "updated_at": func.now(),
        },
    )

    await session.execute(stmt)
    await session.commit()

    return {
        "period": period,
        "revenue_target": float(revenue_target),
        "margin_target_pct": margin_target_pct,
    }


def _estimate_monthly_commission(revenue: Decimal) -> Decimal:
    return revenue * MASTER_COMMISSION_PCT


def _days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


async def get_hourly_finance(
    session: AsyncSession,
    target_date: date,
) -> list[dict]:
    hour_expr = (func.extract("hour", Visit.datetime) + DB_HOUR_SHIFT).label("hour")
    rows = await session.execute(
        select(
            hour_expr,
            Visit.status,
            func.sum(Visit.total_amount).label("revenue"),
        )
        .where(
            func.date(Visit.datetime) == target_date,
        )
        .group_by(hour_expr, Visit.status)
    )

    sale_hour_expr = (func.extract("hour", Sale.datetime) + DB_HOUR_SHIFT).label("hour")
    sale_rows = await session.execute(
        select(
            sale_hour_expr,
            func.sum(Sale.total_amount).label("product_sales"),
        )
        .where(
            func.date(Sale.datetime) == target_date,
        )
        .group_by(sale_hour_expr)
    )

    product_sales_by_hour: dict[int, Decimal] = {}
    total_product_sales = Decimal("0")
    for row in sale_rows:
        hour = int(row.hour) if row.hour else None
        if hour is not None:
            product_sales_by_hour[hour] = Decimal(str(row.product_sales or 0))
            total_product_sales += Decimal(str(row.product_sales or 0))

    if total_product_sales > 0 and not product_sales_by_hour:
        product_sales_by_hour = {h: total_product_sales / len(WORKING_HOURS) for h in WORKING_HOURS}

    hourly: dict[int, dict] = {
        h: {
            "completed": Decimal("0"),
            "scheduled": Decimal("0"),
            "product_sales": Decimal(str(product_sales_by_hour.get(h, 0))),
        }
        for h in WORKING_HOURS
    }

    for row in rows:
        hour = int(row.hour) if row.hour else None
        if hour is None or hour not in hourly:
            continue
        revenue = Decimal(str(row.revenue or 0))
        status = str(row.status or "")
        if status in COMPLETED_STATUSES:
            hourly[hour]["completed"] += revenue
        else:
            hourly[hour]["scheduled"] += revenue

    masters_count = await _get_masters_count(session, target_date)
    break_even = _break_even_revenue(masters_count)

    result = []
    for hour in WORKING_HOURS:
        result.append({
            "hour": f"{hour}:00",
            "completed": float(hourly[hour]["completed"]),
            "scheduled": float(hourly[hour]["scheduled"]),
            "product_sales": float(hourly[hour]["product_sales"]),
            "break_even": float(break_even),
            "masters_count": masters_count,
        })

    return result


async def _get_masters_count(session: AsyncSession, target_date: date) -> int:
    row = await session.scalar(
        select(func.count(func.distinct(Visit.employee_id)))
        .where(func.date(Visit.datetime) == target_date)
    )
    return int(row or 0)
