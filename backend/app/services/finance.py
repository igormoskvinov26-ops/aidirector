"""Financial analysis: marginability, break-even, daily/monthly metrics."""

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import CostModel, PlanTarget, Sale, SaleItem, Visit

WORKING_HOURS = range(10, 22)
DB_HOUR_SHIFT = 1
DEFAULT_MASTERS = 2

COMPLETED_STATUSES = {"completed"}
# Записи, по которым деньги ещё придут. Отмены и неявки сюда не входят:
# складывать несостоявшийся визит с записью на завтра нельзя.
SCHEDULED_STATUSES = {"scheduled"}
COUNTED_STATUSES = COMPLETED_STATUSES | SCHEDULED_STATUSES


@dataclass(frozen=True)
class Costs:
    """Экономика одного дня работы.

    Постоянные расходы уже приведены к дню: аренда и оклады задаются суммой
    в месяц и делятся на число дней в месяце. Переменные — доля от выручки.
    Мастер получает процент, но не меньше гаранта за смену.
    """

    fixed_daily: Decimal
    variable_pct: Decimal
    master_commission_pct: Decimal
    master_min_salary: Decimal


# Аренда 170 000 и доля расходников 3,52% — из отчёта P&L за август 2026.
# Оплата труда задана владельцем: управляющий совмещён со вторым
# администратором на окладе 90 000, сменный администратор получает 4 000 за
# смену. Коммуналка 15 000 и уборка 15 000, налоги 6 000.
# Сменный администратор выходит 15-16 раз в месяц, остальные смены закрывает
# управляющий, поэтому его оплата берётся за месяц, а не за каждый день.
# Итого 296 000 плюс 4 000 x 15,5 = 358 000 в месяц.
# Ставка мастера 40% и гарант 4 000 за смену названы владельцем. По кассовому
# отчёту они не выводятся: выплаты смещены на месяц относительно выручки.
DEFAULT_COSTS = Costs(
    fixed_daily=(
        (Decimal("296000") + Decimal("4000") * Decimal("15.5")) / Decimal("30.4")
    ).quantize(Decimal("0.01")),
    variable_pct=Decimal("0.035"),
    master_commission_pct=Decimal("0.40"),
    master_min_salary=Decimal("4000.00"),
)

# Прежние имена — чтобы не переписывать всё, что на них опиралось.
FIXED_DAILY_COST = DEFAULT_COSTS.fixed_daily
VARIABLE_COST_PCT = DEFAULT_COSTS.variable_pct
MASTER_COMMISSION_PCT = DEFAULT_COSTS.master_commission_pct
MASTER_MIN_SALARY = DEFAULT_COSTS.master_min_salary


async def get_costs(session: AsyncSession, when: date | None = None) -> Costs:
    """Расходы из базы, приведённые к дню указанного месяца.

    Если строка настроек ещё не заведена, возвращаются значения из отчёта за
    август. Молча считать по нулям нельзя: порог безубыточности обнулится и
    любой день покажется прибыльным.
    """
    row = await session.scalar(select(CostModel).order_by(CostModel.id).limit(1))
    if row is None:
        return DEFAULT_COSTS

    when = when or date.today()
    days = Decimal(_days_in_month(when.year, when.month))

    monthly_fixed = (
        row.rent_monthly
        + row.utilities_monthly
        + row.manager_monthly
        + row.cleaning_monthly
        + row.taxes_monthly
        + row.other_fixed_monthly
    )
    # Оплата сменного администратора переводится в месяц по числу его смен и
    # только потом делится на дни. Добавлять её к каждому дню нельзя: он
    # выходит примерно через день, остальное закрывает управляющий.
    monthly_admin = row.admin_per_shift * row.admin_shifts_per_month
    return Costs(
        fixed_daily=((monthly_fixed + monthly_admin) / days).quantize(Decimal("0.01")),
        variable_pct=(row.materials_pct + row.acquiring_pct) / Decimal("100"),
        master_commission_pct=row.master_commission_pct / Decimal("100"),
        master_min_salary=row.master_min_guarantee,
    )


def _compute_margin(
    revenue: Decimal,
    num_masters: int,
    costs: Costs = DEFAULT_COSTS,
) -> dict:
    actual_masters = max(num_masters, 1)
    if revenue <= 0:
        return {
            "margin_rub": Decimal("0"),
            "margin_pct": Decimal("0"),
            "break_even": _break_even_revenue(num_masters, costs),
            "costs": {
                "fixed": costs.fixed_daily,
                "variable": Decimal("0"),
                "master_commission": Decimal("0"),
                "total": costs.fixed_daily,
            },
        }

    variable_cost = revenue * costs.variable_pct

    revenue_per_master = revenue / actual_masters
    master_commission_per = max(
        costs.master_min_salary, revenue_per_master * costs.master_commission_pct
    )
    master_commission = master_commission_per * actual_masters

    total_costs = costs.fixed_daily + variable_cost + master_commission
    margin_rub = revenue - total_costs
    margin_pct = (margin_rub / revenue * 100).quantize(Decimal("0.1"))

    return {
        "margin_rub": margin_rub,
        "margin_pct": margin_pct,
        "break_even": _break_even_revenue(num_masters, costs),
        "costs": {
            "fixed": costs.fixed_daily,
            "variable": variable_cost,
            "master_commission": master_commission,
            "total": total_costs,
        },
    }


def _revenue_for_profit(
    num_masters: int,
    profit: Decimal = Decimal("0"),
    costs: Costs = DEFAULT_COSTS,
) -> Decimal:
    """Какая выручка за день нужна, чтобы получить заданную прибыль.

    Оплата мастера ломает зависимость надвое. Пока выручка на мастера мала,
    он получает гарант — фиксированную сумму, и она входит в расходы как
    постоянная. Выше точки переключения начинает действовать процент, и
    расход растёт вместе с выручкой. Поэтому сначала проверяется режим
    процента, и если полученная выручка в него не попадает — считается по
    гаранту.

    Прибыль, равная нулю, даёт точку безубыточности.
    """
    masters = max(num_masters, 1)
    need = costs.fixed_daily + profit

    denom_high = Decimal("1") - costs.variable_pct - costs.master_commission_pct
    if denom_high > 0 and costs.master_commission_pct > 0:
        rev_high = need / denom_high
        # Точка переключения: выручка на мастера, при которой процент
        # сравнивается с гарантом. При 40% и гаранте 4 000 это 10 000 —
        # прежде это число было записано в коде вручную и ломалось при
        # любой смене ставки.
        switch_per_master = costs.master_min_salary / costs.master_commission_pct
        if rev_high / masters >= switch_per_master:
            return rev_high.quantize(Decimal("0.01"))

    denom_low = Decimal("1") - costs.variable_pct
    rev_low = (need + costs.master_min_salary * masters) / denom_low
    return rev_low.quantize(Decimal("0.01"))


def _break_even_revenue(num_masters: int, costs: Costs = DEFAULT_COSTS) -> Decimal:
    """Выручка, при которой день выходит ровно в ноль."""
    return _revenue_for_profit(num_masters, Decimal("0"), costs)


# Ориентир для интерфейса, пока данные не загружены. В ответы по дням не
# попадает: там всегда считается по фактическому числу мастеров.
DAILY_BREAK_EVEN = _break_even_revenue(DEFAULT_MASTERS)


async def get_daily_finance(
    session: AsyncSession,
    date_from: date,
    date_to: date,
) -> list[dict]:
    """Выручка и пороги по дням периода.

    Кроме порога безубыточности отдаётся revenue_for_plan — выручка, нужная
    в этот день для выполнения плана по прибыли. Обе величины считаются по
    числу мастеров этого дня, поэтому на графике их можно класть рядом со
    столбцами выручки.
    """
    costs = await get_costs(session, date_from)
    plan = await get_current_month_plan(session)
    profit_target = Decimal(str(plan["profit_target"]))
    daily_profit = Decimal("0")
    if profit_target > 0:
        daily_profit = profit_target / Decimal(_days_in_month(date_from.year, date_from.month))

    day_label = func.date(Visit.datetime)

    rows = await session.execute(
        select(
            day_label.label("day"),
            func.sum(
                case((Visit.status.in_(COUNTED_STATUSES), Visit.total_amount), else_=None)
            ).label("revenue"),
            func.sum(
                case((Visit.status.in_(COMPLETED_STATUSES), Visit.total_amount), else_=None)
            ).label("completed_amount"),
            func.sum(
                case((Visit.status.in_(SCHEDULED_STATUSES), Visit.total_amount), else_=None)
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
        margin = _compute_margin(completed, num_masters, costs)

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
            # Порог по фактическому числу мастеров в этот день, а не константа:
            # смена из одного человека и смена из трёх окупаются по-разному.
            "break_even": float(margin["break_even"]),
            "revenue_for_plan": float(
                _revenue_for_profit(num_masters, daily_profit, costs)
            ) if daily_profit > 0 else 0.0,
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
                "break_even": float(_break_even_revenue(1, costs)),
                "revenue_for_plan": float(
                    _revenue_for_profit(1, daily_profit, costs)
                ) if daily_profit > 0 else 0.0,
                "costs": {"fixed": 0, "variable": 0, "master_commission": 0, "total": 0},
            })
        current += timedelta(days=1)

    return filled


COST_FIELDS = (
    "rent_monthly",
    "utilities_monthly",
    "manager_monthly",
    "cleaning_monthly",
    "taxes_monthly",
    "other_fixed_monthly",
    "admin_per_shift",
    "admin_shifts_per_month",
    "materials_pct",
    "acquiring_pct",
    "master_commission_pct",
    "master_min_guarantee",
)


async def get_cost_settings(session: AsyncSession) -> dict:
    """Расходы как их задаёт владелец — суммами в месяц и процентами."""
    row = await session.scalar(select(CostModel).order_by(CostModel.id).limit(1))
    today = date.today()
    days = _days_in_month(today.year, today.month)

    if row is None:
        values = {f: 0.0 for f in COST_FIELDS}
        monthly_fixed = 0.0
        monthly_admin = 0.0
    else:
        values = {f: float(getattr(row, f)) for f in COST_FIELDS}
        monthly_fixed = sum(
            values[f] for f in COST_FIELDS if f.endswith("_monthly")
        )
        monthly_admin = values["admin_per_shift"] * values["admin_shifts_per_month"]

    return {
        **values,
        "admin_monthly_total": round(monthly_admin, 2),
        "fixed_monthly_total": round(monthly_fixed + monthly_admin, 2),
        "fixed_daily": round((monthly_fixed + monthly_admin) / days, 2),
        "days_in_month": days,
        "is_default": row is None,
    }


async def set_cost_settings(session: AsyncSession, values: dict) -> dict:
    """Сохранить расходы. Строка всегда одна, поэтому обновляем её же."""
    row = await session.scalar(select(CostModel).order_by(CostModel.id).limit(1))
    if row is None:
        row = CostModel(id=1)
        session.add(row)

    for field in COST_FIELDS:
        if field in values and values[field] is not None:
            setattr(row, field, Decimal(str(values[field])))

    await session.commit()
    return await get_cost_settings(session)


async def get_plan_fact(session: AsyncSession) -> dict:
    """Сводка текущего месяца для вкладки «План-факт».

    Возвращает три вещи: что уже заработано с начала месяца, какой стоит план
    и таблицу по количеству мастеров на смене — порог безубыточности, сколько
    нужно зарабатывать в день, чтобы догнать план, и сколько выходит на самом
    деле в дни с таким составом смены.
    """
    today = date.today()
    period = today.strftime("%Y-%m")
    days_in_month = _days_in_month(today.year, today.month)
    month_start = today.replace(day=1)
    month_end = today.replace(day=days_in_month)

    costs = await get_costs(session, today)
    services = await _month_services(session, month_start, month_end)
    products = await _month_products(session, month_start, month_end)
    plan = await get_current_month_plan(session)

    earned = services["amount"] + products["amount"]
    target = Decimal(str(plan["profit_target"]))

    # Догоняющий план: остаток делится на оставшиеся дни, включая сегодняшний.
    # Делить месячный план на все дни месяца нельзя — к середине месяца такая
    # цифра перестаёт отвечать на вопрос «сколько нужно сегодня».
    days_left = days_in_month - today.day + 1
    profit_so_far = await _profit_to_date(session, month_start, today, costs)
    remaining = max(target - profit_so_far, Decimal("0"))
    profit_needed_daily = Decimal("0")
    if target > 0:
        profit_needed_daily = (remaining / days_left).quantize(Decimal("0.01"))

    fact_by_masters = await _fact_daily_average_by_masters(session, month_start, today)
    masters_today = await _get_masters_count(session, today)

    rows = []
    for masters in (1, 2, 3):
        fact = fact_by_masters.get(masters)
        break_even = _break_even_revenue(masters, costs)
        # Вот здесь состав смены и начинает влиять: чтобы получить одну и ту же
        # прибыль, при трёх мастерах нужно заработать больше, чем при одном —
        # их гарант и процент вычитаются из той же выручки.
        required = (
            _revenue_for_profit(masters, profit_needed_daily, costs)
            if target > 0
            else Decimal("0")
        )
        rows.append({
            "masters": masters,
            "break_even_daily": float(break_even),
            "plan_daily_required": float(required),
            "plan_per_master": float(
                (required / masters).quantize(Decimal("0.01"))
            ) if required > 0 else 0.0,
            "fact_daily_avg": float(fact["avg"]) if fact else None,
            "fact_days": fact["days"] if fact else 0,
            "is_today": masters == masters_today,
        })

    return {
        "period": period,
        "today": today.isoformat(),
        "days_in_month": days_in_month,
        "days_passed": today.day,
        "days_left": days_left,
        "masters_today": masters_today,
        "fact": {
            "earned_total": float(earned),
            "services_amount": float(services["amount"]),
            "services_count": services["count"],
            "products_amount": float(products["amount"]),
            "products_units": products["units"],
        },
        "plan": {
            "profit_target": float(target),
            "profit_so_far": float(profit_so_far),
            "remaining": float(remaining),
            "profit_needed_daily": float(profit_needed_daily),
            "completion_pct": float(
                (profit_so_far / target * 100).quantize(Decimal("0.1"))
            ) if target > 0 else 0.0,
        },
        "rows": rows,
    }


async def _profit_to_date(
    session: AsyncSession,
    date_from: date,
    date_to: date,
    costs: Costs,
) -> Decimal:
    """Прибыль, набранная с начала месяца.

    Считается по дням, а не от месячных сумм: оплата мастера зависит от
    выручки конкретного дня и от того, сколько человек было на смене, —
    усреднение по месяцу даёт другое число.
    """
    days = await get_daily_finance(session, date_from, date_to)
    total = Decimal("0")
    for day in days:
        earned = Decimal(str(day["completed"])) + Decimal(str(day["product_sales"]))
        if earned <= 0:
            continue
        total += _compute_margin(earned, int(day["masters_count"] or 0), costs)["margin_rub"]
    return total.quantize(Decimal("0.01"))


async def _month_services(session: AsyncSession, date_from: date, date_to: date) -> dict:
    """Выполненные услуги за период: сумма и количество записей."""
    day_label = func.date(Visit.datetime)
    row = (await session.execute(
        select(
            func.coalesce(func.sum(Visit.total_amount), 0).label("amount"),
            func.count(Visit.id).label("count"),
        ).where(
            day_label >= date_from,
            day_label <= date_to,
            Visit.status.in_(COMPLETED_STATUSES),
        )
    )).one()
    return {"amount": Decimal(str(row.amount or 0)), "count": int(row.count or 0)}


async def _month_products(session: AsyncSession, date_from: date, date_to: date) -> dict:
    """Продажи косметики за период: сумма и количество штук.

    Сумма берётся из чеков, а штуки — из позиций в них: один чек может
    содержать несколько единиц, и считать чеки вместо единиц значит занижать.
    """
    sale_day = func.date(Sale.datetime)
    amount = await session.scalar(
        select(func.coalesce(func.sum(Sale.total_amount), 0)).where(
            sale_day >= date_from,
            sale_day <= date_to,
        )
    )
    units = await session.scalar(
        select(func.coalesce(func.sum(SaleItem.quantity), 0))
        .select_from(SaleItem)
        .join(Sale, SaleItem.sale_id == Sale.id)
        .where(
            sale_day >= date_from,
            sale_day <= date_to,
        )
    )
    return {"amount": Decimal(str(amount or 0)), "units": int(units or 0)}


async def _fact_daily_average_by_masters(
    session: AsyncSession,
    date_from: date,
    date_to: date,
) -> dict[int, dict]:
    """Средняя выручка дня в разрезе количества мастеров на смене.

    Считается только по прошедшим дням, в которые была хоть какая-то выручка:
    выходные и пустые дни занижали бы среднее, отвечая не на тот вопрос.
    """
    days = await get_daily_finance(session, date_from, date_to)

    buckets: dict[int, list[Decimal]] = {}
    for day in days:
        masters = int(day["masters_count"] or 0)
        earned = Decimal(str(day["completed"])) + Decimal(str(day["product_sales"]))
        if masters <= 0 or earned <= 0:
            continue
        buckets.setdefault(masters, []).append(earned)

    return {
        masters: {
            "avg": (sum(values) / len(values)).quantize(Decimal("0.01")),
            "days": len(values),
        }
        for masters, values in buckets.items()
    }


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
        margin_pct = Decimal("0")
        if revenue > 0:
            margin_pct = (margin_rub / revenue * 100).quantize(Decimal("0.1"))

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
            "profit_target": float(row.profit_target),
            "margin_target_pct": float(row.margin_target_pct),
        }

    return {
        "period": period,
        "profit_target": 0,
        "margin_target_pct": 30.0,
    }


async def set_monthly_plan(
    session: AsyncSession,
    period: str,
    profit_target: Decimal,
    margin_target_pct: float = 30.0,
) -> dict:
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    stmt = pg_insert(PlanTarget).values(
        period=period,
        profit_target=profit_target,
        margin_target_pct=margin_target_pct,
    ).on_conflict_do_update(
        index_elements=["period"],
        set_={
            "profit_target": profit_target,
            "margin_target_pct": margin_target_pct,
            "updated_at": func.now(),
        },
    )

    await session.execute(stmt)
    await session.commit()

    return {
        "period": period,
        "profit_target": float(profit_target),
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
        elif status in SCHEDULED_STATUSES:
            hourly[hour]["scheduled"] += revenue

    masters_count = await _get_masters_count(session, target_date)
    costs = await get_costs(session, target_date)
    break_even = _break_even_revenue(masters_count, costs)

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
