"""Financial analysis: marginability, break-even, daily/monthly metrics."""

import calendar
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_CEILING, Decimal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.models import CostModel, Employee, PlanTarget, Sale, SaleItem, Visit

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

    Мастер получает процент с услуг и отдельный, меньший процент с проданной
    косметики, но в сумме не меньше гаранта за смену. Гаранты у мастеров
    разные, поэтому здесь список, а не одно число: при двух работающих важно,
    какие именно двое вышли.
    """

    fixed_daily: Decimal
    variable_pct: Decimal
    master_commission_pct: Decimal
    product_commission_pct: Decimal
    guarantees: tuple[Decimal, ...]

    def shift_guarantees(self, num_masters: int) -> tuple[Decimal, ...]:
        """Гаранты для смены из указанного числа мастеров.

        Берутся самые крупные: кто именно выйдет, заранее неизвестно, и
        занизить планку хуже, чем завысить. День, посчитанный прибыльным по
        ошибке, узнаётся только в конце месяца.
        """
        if num_masters <= 0:
            num_masters = 1
        ordered = sorted(self.guarantees, reverse=True) or [Decimal("0")]
        picked = list(ordered[:num_masters])
        while len(picked) < num_masters:
            picked.append(ordered[-1])
        return tuple(picked)


# Постоянные расходы — 389 117 ₽ в месяц.
#
# Первые четыре статьи взяты из выгрузки YCLIENTS за август 2026 — первый
# месяц, выгруженный целиком (до починки постраничного обхода приходила
# девятая часть операций):
#
#     аренда                 170 000
#     уборка                  15 000
#     прочие расходы          17 137
#     бизнес-расходы          11 980
#                            --------
#                            214 117
#
# Остальное названо владельцем 16.09.2026. В выгрузке этого нет: оплата труда
# лежит там одной статьёй «Зарплата персонала» вместе с оплатой мастеров, а
# коммуналка через кассу YCLIENTS не проходит вовсе.
#
#     управляющий             90 000
#     сменный администратор   64 000   4 000 за смену, 16 смен в месяц
#     налоги                   6 000
#     коммуналка              15 000
#                            --------
#                            175 000
#
# Число смен администратора — ровно 16, без поправки на длину месяца: так
# указал владелец. Прежние 15,5 были моей интерполяцией «15-16 смен» и в
# расчёт попали без подтверждения.
#
# Разбор оставлен на память о происхождении числа; расчёт ведётся одной
# суммой, и правится она одним полем.
#
# Оплаты мастеров и расходников в этой сумме НЕТ: они считаются процентом от
# выручки и попади они ещё и сюда — учлись бы дважды. Именно поэтому число
# нельзя получить из YCLIENTS простым сложением: статья «Зарплата персонала»
# смешивает постоянную часть с процентной, и через API их не разделить.
#
# Коммуналки в выгрузке нет ни отдельной статьёй, ни внутри прочих. Владелец
# подтвердил, что она платится и составляет фиксированные 15 000 — на этом
# основании она в сумме, хотя в кассе её не видно.
#
# Доля расходников проверена по той же выгрузке: 29 060 из 824 465 = 3,52%,
# в настройках стоит 3,5%. Ставка мастера 40% с услуг и 10% с косметики,
# гарант 4 000 за смену у всех — названы владельцем; по кассе они не
# выводятся, выплаты смещены на месяц относительно выручки. Гаранты берутся
# из настроек оплаты барберов: сейчас они одинаковы, но заданы пофамильно, и
# расчёт выдержит, если разойдутся.
DEFAULT_FIXED_MONTHLY = Decimal("389117")

DEFAULT_COSTS = Costs(
    fixed_daily=(DEFAULT_FIXED_MONTHLY / Decimal("30.4")).quantize(Decimal("0.01")),
    variable_pct=Decimal("0.035"),
    master_commission_pct=Decimal("0.40"),
    product_commission_pct=Decimal("0.10"),
    guarantees=(Decimal("4000.00"), Decimal("4000.00"), Decimal("4000.00")),
)

# Прежние имена — чтобы не переписывать всё, что на них опиралось.
FIXED_DAILY_COST = DEFAULT_COSTS.fixed_daily
VARIABLE_COST_PCT = DEFAULT_COSTS.variable_pct
MASTER_COMMISSION_PCT = DEFAULT_COSTS.master_commission_pct


def _guarantees_from_settings() -> tuple[Decimal, ...]:
    """Гаранты барберов из настроек оплаты.

    Источник один — список барберов: там они заданы пофамильно и там же их
    правят. Дублировать это число в таблице расходов значит однажды поменять
    его в одном месте и забыть про другое.
    """
    values = [
        Decimal(str(rule.get("guarantee", 0)))
        for rule in getattr(settings, "barber_payroll_rules", [])
    ]
    return tuple(v for v in values if v > 0) or DEFAULT_COSTS.guarantees


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

    return Costs(
        fixed_daily=(row.fixed_monthly / days).quantize(Decimal("0.01")),
        variable_pct=(row.materials_pct + row.acquiring_pct) / Decimal("100"),
        master_commission_pct=row.master_commission_pct / Decimal("100"),
        product_commission_pct=row.product_commission_pct / Decimal("100"),
        guarantees=_guarantees_from_settings(),
    )


def _one_master_pay(
    services: Decimal,
    products: Decimal,
    guarantee: Decimal,
    costs: Costs,
) -> Decimal:
    """Сколько получит один мастер за свою работу за день.

    Процент со своих услуг плюс процент со своих продаж косметики, но не
    меньше гаранта за смену.
    """
    earned = (
        max(Decimal(str(services)), Decimal("0")) * costs.master_commission_pct
        + max(Decimal(str(products)), Decimal("0")) * costs.product_commission_pct
    )
    return max(guarantee, earned)


def payout_by_master(
    per_master: Sequence[tuple[Decimal, Decimal]],
    costs: Costs,
) -> Decimal:
    """Фонд оплаты за день по фактической выработке каждого.

    Гарант платится персонально, поэтому складывать выручку всех и делить
    поровну нельзя. Мастер, сделавший 25 000, получит свои 10 000 процентом, а
    его напарник с пятью тысячами — 4 000 гарантом, и вместе это 14 000, а не
    12 000, как выходит при равном делении. Разницу салон доплачивает из
    прибыли, и она тем больше, чем сильнее перекос.
    """
    guarantees = costs.shift_guarantees(len(per_master))
    return sum(
        (
            _one_master_pay(services, products, guarantee, costs)
            # strict: длины обязаны совпасть — гаранты берутся по числу
            # мастеров. Расхождение означало бы, что кому-то не досталось
            # гаранта, и лучше узнать об этом сразу.
            for (services, products), guarantee in zip(per_master, guarantees, strict=True)
        ),
        Decimal("0"),
    )


def _master_payout(
    service_revenue: Decimal,
    product_revenue: Decimal,
    num_masters: int,
    costs: Costs,
) -> Decimal:
    """Оценка фонда оплаты, когда выработка каждого неизвестна.

    Выручка делится поровну — это самый благоприятный для салона случай:
    при равном делении никто не проваливается под гарант, и фонд оплаты
    минимален. Любой перекос его только увеличивает. Годится для прикидки
    порога на будущее, где выработку знать неоткуда; за прошедшие дни надо
    брать payout_by_master и настоящие цифры.
    """
    masters = max(num_masters, 1)
    services = max(Decimal(str(service_revenue)), Decimal("0")) / masters
    products = max(Decimal(str(product_revenue)), Decimal("0")) / masters
    return payout_by_master([(services, products)] * masters, costs)


def _day_costs(
    service_revenue: Decimal,
    product_revenue: Decimal,
    num_masters: int,
    costs: Costs,
    per_master: Sequence[tuple[Decimal, Decimal]] | None = None,
) -> dict:
    """Расходы и прибыль дня без порога безубыточности.

    Порог сюда не входит намеренно. Он считается подбором выручки, при которой
    прибыль равна нулю, то есть через эту же функцию — если положить его
    внутрь, расчёт начнёт вызывать сам себя без конца.
    """
    revenue = max(Decimal(str(service_revenue)), Decimal("0")) + max(
        Decimal(str(product_revenue)), Decimal("0")
    )
    variable_cost = revenue * costs.variable_pct
    # Если известно, кто сколько наработал, считаем точно. Оценка поровну —
    # только для дней, которых ещё не было.
    master_commission = (
        payout_by_master(per_master, costs)
        if per_master
        else _master_payout(service_revenue, product_revenue, num_masters, costs)
    )
    total_costs = costs.fixed_daily + variable_cost + master_commission

    margin_pct = Decimal("0")
    if revenue > 0:
        margin_pct = ((revenue - total_costs) / revenue * 100).quantize(Decimal("0.1"))

    return {
        "margin_rub": revenue - total_costs,
        "margin_pct": margin_pct,
        "costs": {
            "fixed": costs.fixed_daily,
            "variable": variable_cost,
            "master_commission": master_commission,
            "total": total_costs,
        },
    }


def _compute_margin(
    service_revenue: Decimal,
    product_revenue: Decimal = Decimal("0"),
    num_masters: int = 1,
    costs: Costs = DEFAULT_COSTS,
    per_master: Sequence[tuple[Decimal, Decimal]] | None = None,
) -> dict:
    """Прибыль дня. Услуги и косметика разведены: ставки по ним разные."""
    result = _day_costs(service_revenue, product_revenue, num_masters, costs, per_master)
    result["break_even"] = _break_even_revenue(num_masters, costs)
    return result


def _revenue_for_profit(
    num_masters: int,
    profit: Decimal = Decimal("0"),
    costs: Costs = DEFAULT_COSTS,
    product_revenue: Decimal = Decimal("0"),
) -> Decimal:
    """Какая выручка по услугам нужна, чтобы получить заданную прибыль.

    Прежде это решалось формулой, но она держалась на двух допущениях: все
    мастера с одинаковым гарантом и единая ставка со всей выручки. Ни то, ни
    другое не верно — гаранты разные, а с косметики процент свой. Формула для
    такого случая разваливается на разбор режимов, по одному на каждого
    мастера, и каждый из них легко написать неправильно.

    Поэтому здесь двоичный поиск. Прибыль строго растёт вместе с выручкой:
    каждый добавленный рубль оставляет в кассе долю, которая всегда больше
    нуля. Значит, решение единственное и находится делением отрезка пополам.

    Продажи косметики по умолчанию нулевые: сколько её купят, заранее
    неизвестно, а их отсутствие — вариант осторожный. Косметика приносит
    больше, чем стоит, и с ней порог только снизится.

    Прибыль, равная нулю, даёт точку безубыточности.
    """
    masters = max(num_masters, 1)

    def margin_at(service_revenue: Decimal) -> Decimal:
        return _day_costs(service_revenue, product_revenue, masters, costs)["margin_rub"]

    low = Decimal("0")
    if margin_at(low) >= profit:
        return low

    # Верхняя граница подбирается удвоением: сколько бы ни стоила смена,
    # достаточно большая выручка её перекроет.
    high = max(costs.fixed_daily + profit, Decimal("1000"))
    for _ in range(60):
        if margin_at(high) >= profit:
            break
        high *= 2
    else:  # pragma: no cover - недостижимо при доле расходов меньше единицы
        raise ValueError("Прибыль недостижима: переменные расходы съедают всю выручку")

    cent = Decimal("0.01")
    while high - low > cent:
        middle = (low + high) / 2
        if margin_at(middle) >= profit:
            high = middle
        else:
            low = middle

    return high.quantize(cent)


def _break_even_revenue(num_masters: int, costs: Costs = DEFAULT_COSTS) -> Decimal:
    """Выручка по услугам, при которой день выходит ровно в ноль."""
    return _revenue_for_profit(num_masters, Decimal("0"), costs)


async def _daily_master_breakdown(
    session: AsyncSession,
    date_from: date,
    date_to: date,
) -> dict[str, list[tuple[Decimal, Decimal]]]:
    """Выработка каждого мастера по дням: услуги и косметика отдельно.

    Нужна, чтобы считать фонд оплаты по-настоящему: гарант платится
    персонально, и при неравной выработке сумма выходит больше, чем при
    делении общей выручки поровну.
    """
    day = func.date(Visit.datetime)
    service_rows = await session.execute(
        select(
            day.label("day"),
            Visit.employee_id,
            func.coalesce(func.sum(Visit.total_amount), 0).label("amount"),
        )
        .where(
            day >= date_from,
            day <= date_to,
            Visit.status.in_(COMPLETED_STATUSES),
        )
        .group_by(day, Visit.employee_id)
    )

    sale_day = func.date(Sale.datetime)
    product_rows = await session.execute(
        select(
            sale_day.label("day"),
            Sale.employee_id,
            func.coalesce(func.sum(Sale.total_amount), 0).label("amount"),
        )
        .where(
            sale_day >= date_from,
            sale_day <= date_to,
            Sale.employee_id.is_not(None),
        )
        .group_by(sale_day, Sale.employee_id)
    )

    by_day: dict[str, dict[int, list[Decimal]]] = {}
    for row in service_rows:
        bucket = by_day.setdefault(str(row.day), {})
        entry = bucket.setdefault(int(row.employee_id), [Decimal("0"), Decimal("0")])
        entry[0] += Decimal(str(row.amount or 0))
    for row in product_rows:
        bucket = by_day.setdefault(str(row.day), {})
        entry = bucket.setdefault(int(row.employee_id), [Decimal("0"), Decimal("0")])
        entry[1] += Decimal(str(row.amount or 0))

    # Внутри дня сортируем по убыванию выработки: самым крупным гарантам
    # достаются мастера, заработавшие больше всех, и при равных гарантах
    # порядок ни на что не влияет.
    return {
        day_str: [
            (services, products)
            for services, products in sorted(
                masters.values(), key=lambda pair: pair[0] + pair[1], reverse=True
            )
        ]
        for day_str, masters in by_day.items()
    }


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
    breakdown = await _daily_master_breakdown(session, date_from, date_to)

    # Границы зон зависят только от числа мастеров, а оно повторяется изо дня
    # в день. Считаем по одному разу на состав смены, а не на каждый день:
    # подбор границы стоит полсотни итераций.
    zone_cache: dict[int, tuple[Decimal, Decimal]] = {}

    def zone_bounds(masters: int) -> tuple[Decimal, Decimal]:
        masters = max(masters, 1)
        if masters not in zone_cache:
            zone_cache[masters] = (
                ceil_thousand(_break_even_revenue(masters, costs)),
                ceil_thousand(
                    _break_even_for_split(
                        [Decimal("1")] + [Decimal("0")] * (masters - 1), costs
                    )
                ),
            )
        return zone_cache[masters]
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
        products = sales_by_day.get(day_str, Decimal("0"))
        # Услуги и косметика передаются раздельно: ставка мастера по ним разная.
        # Разбивка по мастерам — чтобы гарант считался персонально, а не от
        # выручки, поделённой поровну.
        margin = _compute_margin(
            completed, products, num_masters, costs, breakdown.get(day_str)
        )
        low, high = zone_bounds(num_masters)

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
            "zone_low": float(low),
            "zone_high": float(high),
            # Зона только для дней, в которые что-то заработано: у будущих
            # записей раскрашивать нечего, они ещё не состоялись.
            "zone": revenue_zone(completed, low, high) if completed > 0 else None,
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
                "zone_low": float(zone_bounds(1)[0]),
                "zone_high": float(zone_bounds(1)[1]),
                "zone": None,
                "costs": {"fixed": 0, "variable": 0, "master_commission": 0, "total": 0},
            })
        current += timedelta(days=1)

    return filled


COST_FIELDS = (
    "fixed_monthly",
    "materials_pct",
    "acquiring_pct",
    "master_commission_pct",
    "product_commission_pct",
)


async def get_cost_settings(session: AsyncSession) -> dict:
    """Расходы как их задаёт владелец — суммой в месяц и процентами."""
    row = await session.scalar(select(CostModel).order_by(CostModel.id).limit(1))
    today = date.today()
    days = _days_in_month(today.year, today.month)

    if row is None:
        values = {f: 0.0 for f in COST_FIELDS}
    else:
        values = {f: float(getattr(row, f)) for f in COST_FIELDS}

    return {
        **values,
        "fixed_daily": round(values["fixed_monthly"] / days, 2),
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


def ceil_thousand(value: Decimal) -> Decimal:
    """Округление вверх до тысяч.

    Пороги показываются круглыми: сотни рублей ничего не решают, а «21 000»
    запоминается и проверяется в уме, чего не скажешь про «20 843». Вверх, а
    не к ближайшему, — чтобы округление не опустило планку ниже настоящей.
    """
    return (value / 1000).to_integral_value(rounding=ROUND_CEILING) * 1000


def revenue_zone(services: Decimal, low: Decimal, high: Decimal) -> str:
    """В какую из трёх зон попал день.

    red    — ниже порога при любом распределении выручки, день убыточен;
    amber  — между порогами, исход зависит от того, как легла выручка;
    green  — выше верхнего порога, день прибыльный при любом раскладе.
    """
    if services < low:
        return "red"
    if services < high:
        return "amber"
    return "green"


async def _today_by_master(session: AsyncSession, day: date) -> list[dict]:
    """Кто сколько сделал за день — поимённо.

    Нужно, чтобы считать день по-настоящему: гарант платится персонально, и
    два мастера с одинаковой общей выручкой обходятся салону по-разному в
    зависимости от того, как она между ними легла.
    """
    day_expr = func.date(Visit.datetime)
    service_rows = await session.execute(
        select(
            Employee.id,
            Employee.name,
            func.coalesce(func.sum(Visit.total_amount), 0).label("amount"),
        )
        .join(Visit, Visit.employee_id == Employee.id)
        .where(day_expr == day, Visit.status.in_(COMPLETED_STATUSES))
        .group_by(Employee.id, Employee.name)
    )

    sale_expr = func.date(Sale.datetime)
    product_rows = await session.execute(
        select(
            Sale.employee_id,
            func.coalesce(func.sum(Sale.total_amount), 0).label("amount"),
        )
        .where(sale_expr == day, Sale.employee_id.is_not(None))
        .group_by(Sale.employee_id)
    )
    products = {int(r.employee_id): Decimal(str(r.amount or 0)) for r in product_rows}

    masters = [
        {
            "employee_id": int(row.id),
            "name": row.name,
            "services": Decimal(str(row.amount or 0)),
            "products": products.get(int(row.id), Decimal("0")),
        }
        for row in service_rows
    ]
    # Продавший косметику, но никого не постригший, тоже вышел на смену.
    known = {m["employee_id"] for m in masters}
    for employee_id, amount in products.items():
        if employee_id not in known:
            masters.append({
                "employee_id": employee_id,
                "name": "—",
                "services": Decimal("0"),
                "products": amount,
            })

    masters.sort(key=lambda m: m["services"] + m["products"], reverse=True)
    return masters


def _break_even_for_split(
    shares: Sequence[Decimal],
    costs: Costs,
    product_revenue: Decimal = Decimal("0"),
) -> Decimal:
    """Выручка по услугам, нужная для нуля при заданном распределении.

    Доли — то, как выручка ложится между мастерами. Порог от них зависит:
    мастер, не добравший до гаранта, обходится салону дороже, чем тот же
    рубль, заработанный его напарником сверх гаранта.
    """
    total_share = sum(shares, Decimal("0"))
    if total_share <= 0:
        shares = [Decimal("1")] * max(len(shares), 1)
        total_share = Decimal(len(shares))
    normalized = [s / total_share for s in shares]

    def margin_at(revenue: Decimal) -> Decimal:
        per_master = [
            (revenue * part, product_revenue * part) for part in normalized
        ]
        payout = payout_by_master(per_master, costs)
        return revenue + product_revenue - costs.fixed_daily - (
            revenue + product_revenue
        ) * costs.variable_pct - payout

    low, high = Decimal("0"), max(costs.fixed_daily * 4, Decimal("10000"))
    for _ in range(60):
        if margin_at(high) >= 0:
            break
        high *= 2
    while high - low > Decimal("0.01"):
        middle = (low + high) / 2
        if margin_at(middle) >= 0:
            high = middle
        else:
            low = middle
    return high.quantize(Decimal("0.01"))


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

    # Сегодняшний день считается по факту: кто сколько сделал — известно,
    # и допущений о распределении не требуется.
    today_masters = await _today_by_master(session, today)
    today_services = sum((m["services"] for m in today_masters), Decimal("0"))
    today_products = sum((m["products"] for m in today_masters), Decimal("0"))
    today_payout = payout_by_master(
        [(m["services"], m["products"]) for m in today_masters], costs
    ) if today_masters else Decimal("0")
    today_margin = _day_costs(
        today_services,
        today_products,
        len(today_masters) or 1,
        costs,
        per_master=[(m["services"], m["products"]) for m in today_masters] or None,
    )
    today_break_even = _break_even_for_split(
        [m["services"] for m in today_masters] or [Decimal("1")],
        costs,
        today_products,
    )

    # Границы зон для сегодняшнего состава смены. Округляются вверх до тысяч
    # и в таком виде участвуют в раскраске: иначе выручка 20 900 при
    # показанном пороге 21 000 подсветилась бы как достаточная.
    on_shift = len(today_masters) or 1
    zone_low = ceil_thousand(_break_even_revenue(on_shift, costs))
    zone_high = ceil_thousand(
        _break_even_for_split([Decimal("1")] + [Decimal("0")] * (on_shift - 1), costs)
    )

    rows = []
    for masters in (1, 2, 3):
        fact = fact_by_masters.get(masters)
        break_even = _break_even_revenue(masters, costs)
        # Худший случай: один тянет всю выручку, остальные сидят на гаранте.
        # Разница с равномерным делением и есть цена простоя.
        break_even_worst = _break_even_for_split(
            [Decimal("1")] + [Decimal("0")] * (masters - 1), costs
        )
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
            "break_even_daily": float(ceil_thousand(break_even)),
            "break_even_worst": float(ceil_thousand(break_even_worst)),
            "break_even_exact": float(break_even),
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
        "today_detail": {
            "masters": [
                {
                    "name": m["name"],
                    "services": float(m["services"]),
                    "products": float(m["products"]),
                    "payout": float(
                        _one_master_pay(
                            m["services"],
                            m["products"],
                            costs.shift_guarantees(len(today_masters))[i],
                            costs,
                        )
                    ),
                    "on_guarantee": bool(
                        m["services"] * costs.master_commission_pct
                        + m["products"] * costs.product_commission_pct
                        < costs.shift_guarantees(len(today_masters))[i]
                    ),
                }
                for i, m in enumerate(today_masters)
            ],
            "revenue": float(today_services + today_products),
            "payout": float(today_payout),
            "fixed": float(costs.fixed_daily),
            "variable": float(today_margin["costs"]["variable"]),
            "margin": float(today_margin["margin_rub"]),
            "break_even": float(ceil_thousand(today_break_even)),
            "to_break_even": float(
                max(ceil_thousand(today_break_even) - today_services, Decimal("0"))
            ),
            "zone_low": float(zone_low),
            "zone_high": float(zone_high),
            "zone": revenue_zone(today_services, zone_low, zone_high),
            "services": float(today_services),
        },
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
        services = Decimal(str(day["completed"]))
        products = Decimal(str(day["product_sales"]))
        if services + products <= 0:
            continue
        margin = _compute_margin(services, products, int(day["masters_count"] or 0), costs)
        total += margin["margin_rub"]
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
