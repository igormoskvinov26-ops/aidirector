"""KPI calculation service — computes all business metrics."""

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from loguru import logger
from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.models import (
    Client,
    DailyMetrics,
    Employee,
    MonthlyMetrics,
    Visit,
    VisitService,
)
from app.repositories.repositories import MetricsRepository


async def calculate_daily_metrics(
    session: AsyncSession,
    target_date: date | None = None,
    employee_id: int | None = None,
) -> dict:
    target_date = target_date or date.today()

    base_query = select(Visit).where(
        func.date(Visit.datetime) == target_date,
    )
    if employee_id:
        base_query = base_query.where(Visit.employee_id == employee_id)

    result = await session.execute(base_query)
    visits = list(result.scalars().all())

    total_revenue = Decimal("0")
    completed = 0
    cancelled = 0
    no_show = 0
    new_clients = 0
    repeat_clients = 0
    unique_clients = set()
    total_length = 0

    for v in visits:
        if v.status in ("completed", "finished", "1"):
            completed += 1
            total_revenue += v.total_amount
            total_length += v.length_minutes
        elif v.status in ("canceled", "cancelled"):
            cancelled += 1
        elif v.status in ("noshow", "no_show", "2"):
            no_show += 1

        if v.client_id:
            unique_clients.add(v.client_id)
            if v.is_new_client:
                new_clients += 1
            else:
                repeat_clients += 1

    total_visits = len(visits)
    avg_check = Decimal(str(round(total_revenue / completed))) if completed > 0 else Decimal("0")

    working_minutes = 12 * 60 if employee_id else (len(unique_clients) * 12 * 60) or 720
    utilization_pct = (
        Decimal(str(round(total_length / working_minutes * 100, 1))) if working_minutes > 0 else Decimal("0")
    )

    metrics = {
        "total_revenue": total_revenue,
        "total_visits": total_visits,
        "avg_check": avg_check,
        "new_clients": new_clients,
        "repeat_clients": repeat_clients,
        "cancelled": cancelled,
        "no_show": no_show,
        "product_sales": Decimal("0"),
        "utilization_pct": utilization_pct,
    }

    await MetricsRepository.upsert_daily(session, target_date, employee_id, metrics)
    return metrics


async def calculate_monthly_metrics(
    session: AsyncSession,
    year: int,
    month: int,
    employee_id: int | None = None,
) -> dict:
    period = f"{year}-{str(month).zfill(2)}"
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end_date = date(year, month + 1, 1) - timedelta(days=1)

    base_query = select(Visit).where(
        and_(
            func.date(Visit.datetime) >= start_date,
            func.date(Visit.datetime) <= end_date,
        )
    )
    if employee_id:
        base_query = base_query.where(Visit.employee_id == employee_id)

    result = await session.execute(base_query)
    visits = list(result.scalars().all())

    total_revenue = Decimal("0")
    completed = 0
    cancelled = 0
    no_show = 0
    new_clients = 0
    repeat_clients = 0
    unique_clients = set()
    product_sales = Decimal("0")

    for v in visits:
        if v.status in ("completed", "finished", "1"):
            completed += 1
            total_revenue += v.total_amount
        elif v.status in ("canceled", "cancelled"):
            cancelled += 1
        elif v.status in ("noshow", "no_show", "2"):
            no_show += 1

        if v.client_id:
            unique_clients.add(v.client_id)
            if v.is_new_client:
                new_clients += 1
            else:
                repeat_clients += 1

    client_result = await session.execute(
        select(Client).where(
            and_(
                Client.first_visit_date >= start_date,
                Client.first_visit_date <= end_date,
            )
        )
    )
    first_visit_clients = list(client_result.scalars().all())
    new_clients = len(first_visit_clients)

    all_clients_result = await session.execute(select(Client))
    all_clients = list(all_clients_result.scalars().all())

    total_spent = sum(c.total_spent for c in all_clients)
    total_client_visits = sum(c.total_visits for c in all_clients)

    ltv = Decimal(str(round(total_spent / len(all_clients), 2))) if all_clients else Decimal("0")
    total_visits = len(visits)
    avg_check = Decimal(str(round(total_revenue / completed))) if completed > 0 else Decimal("0")

    retention_pct = Decimal("0")
    if repeat_clients + new_clients > 0:
        retention_pct = Decimal(str(round(repeat_clients / (repeat_clients + new_clients) * 100, 1)))

    cancellation_pct = Decimal("0")
    if total_visits > 0:
        cancellation_pct = Decimal(str(round((cancelled + no_show) / total_visits * 100, 1)))

    metrics = {
        "total_revenue": total_revenue,
        "total_visits": total_visits,
        "avg_check": avg_check,
        "new_clients": new_clients,
        "retention_pct": retention_pct,
        "ltv": ltv,
        "cancellation_pct": cancellation_pct,
        "product_sales": product_sales,
        "fot": Decimal("0"),
        "expenses": Decimal("0"),
        "profit": total_revenue,
    }

    await MetricsRepository.upsert_monthly(session, period, employee_id, metrics)
    return metrics


async def calculate_all_daily(
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict:
    if date_from is None:
        date_from = date.today() - timedelta(days=30)
    if date_to is None:
        date_to = date.today()

    stats = {"days": 0}
    current = date_from

    async with async_session() as session:
        while current <= date_to:
            await calculate_daily_metrics(session, current)
            stats["days"] += 1
            current += timedelta(days=1)

    logger.info(f"Daily metrics calculated for {stats['days']} days")
    return stats


async def calculate_all_monthly(
    year_from: int, month_from: int, year_to: int, month_to: int
) -> dict:
    stats = {"months": 0}

    async with async_session() as session:
        for year in range(year_from, year_to + 1):
            start_month = month_from if year == year_from else 1
            end_month = month_to if year == year_to else 12
            for month in range(start_month, end_month + 1):
                await calculate_monthly_metrics(session, year, month)
                stats["months"] += 1

    logger.info(f"Monthly metrics calculated for {stats['months']} months")
    return stats


async def get_dashboard_data(
    session: AsyncSession,
    date_from: date,
    date_to: date,
) -> dict:
    period_str = f"{date_from.isoformat()} → {date_to.isoformat()}"

    daily = await MetricsRepository.get_daily_range(session, date_from, date_to)
    monthly = await MetricsRepository.get_monthly_range(
        session, date_from.strftime("%Y-%m"), date_to.strftime("%Y-%m")
    )

    if not daily and not monthly:
        return {"period": period_str, "kpis": {}, "revenue_trend": [], "top_masters": [], "top_services": []}

    total_revenue = sum(d.total_revenue for d in daily)
    total_visits = sum(d.total_visits for d in daily)
    avg_check = Decimal(str(round(total_revenue / total_visits, 2))) if total_visits > 0 else Decimal("0")

    new_clients = sum(d.new_clients for d in daily)
    repeat_clients = sum(d.repeat_clients for d in daily)
    retention_pct = (
        round(repeat_clients / (new_clients + repeat_clients) * 100, 1)
        if (new_clients + repeat_clients) > 0
        else 0.0
    )

    monthly_data = monthly[-1] if monthly else None
    ltv = monthly_data.ltv if monthly_data else Decimal("0")
    product_sales = Decimal("0")
    profit = total_revenue

    cancellation_pct = 0.0
    if total_visits > 0:
        cancelled = sum(d.cancelled for d in daily) + sum(d.no_show for d in daily)
        cancellation_pct = round(cancelled / total_visits * 100, 1)

    kpis = {
        "total_revenue": str(total_revenue),
        "avg_check": str(avg_check),
        "total_visits": total_visits,
        "new_clients": new_clients,
        "repeat_clients": repeat_clients,
        "retention_pct": retention_pct,
        "ltv": str(ltv),
        "cancellation_pct": cancellation_pct,
        "product_sales": str(product_sales),
        "profit": str(profit),
    }

    revenue_trend = [
        {
            "date": str(d.date),
            "revenue": str(d.total_revenue),
            "visits": d.total_visits,
            "avg_check": str(d.avg_check),
        }
        for d in daily
    ]

    # Top masters per visit
    master_metrics = defaultdict(lambda: {"visits": 0, "revenue": Decimal("0")})
    master_info = {}

    emp_result = await session.execute(select(Employee))
    for emp in emp_result.scalars().all():
        master_info[emp.id] = emp

    visit_result = await session.execute(
        select(Visit).where(
            and_(
                func.date(Visit.datetime) >= date_from,
                func.date(Visit.datetime) <= date_to,
            )
        )
    )
    for v in visit_result.scalars().all():
        mid = v.employee_id
        master_metrics[mid]["visits"] += 1
        master_metrics[mid]["revenue"] += v.total_amount

    top_masters = []
    for mid, data in sorted(master_metrics.items(), key=lambda x: x[1]["revenue"], reverse=True)[:10]:
        emp = master_info.get(mid)
        top_masters.append({
            "name": emp.name if emp else f"#{mid}",
            "avatar_url": emp.avatar_url if emp else None,
            "visits": data["visits"],
            "revenue": str(data["revenue"]),
            "avg_check": str(round(data["revenue"] / data["visits"], 2)) if data["visits"] > 0 else "0",
            "retention_pct": 0.0,
            "product_sales": "0",
        })

    return {
        "period": period_str,
        "kpis": kpis,
        "revenue_trend": revenue_trend,
        "top_masters": top_masters,
        "top_services": [],
        "new_clients_trend": [],
        "cancellation_rate": cancellation_pct,
    }
