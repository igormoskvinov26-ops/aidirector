"""Страница «Финансы»: поступления, расчётные остатки, сверка с банком, расходы.

Источники (решение владельца 02.10.2026):
  * наличка и безнал — из закрытий смены (`shifts.closing_snapshot.money`);
  * оборот по карте — из загруженных отчётов банка по эквайрингу;
  * расходы и прочие движения денег — кассовые транзакции YCLIENTS;
  * стартовые остатки и долг по другому счёту — вносит владелец вручную.

Расчётный остаток = внесённая цифра на дату + поступления после неё по
закрытиям смены + движения по счетам, не связанные с продажами (расходы,
инкассация, внесения). Дни без закрытой смены не угадываются: они выводятся
списком, а остаток считается по закрытым дням.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.models import Shift
from app.services import acquiring, cash_balances
from app.services import barber_month as bm
from app.services.cache import cached
from app.services.monthly_report import MOSCOW, parse_month, prev_month

ПРОДАЖИ = ("service", "goods_transaction")
ДОПУСК = Decimal("1")  # расхождение до рубля считаем совпадением
D0 = Decimal(0)

# Статьи, которые не являются тратой: деньги просто переехали между кассой и счётом.
ПЕРЕВОДЫ = ("инкасс", "перевод", "перемещ", "снятие", "внесен", "пополнение кассы")
ГРУППЫ = (
    ("ФОТ", ("зарплат", "оклад", "аванс", "премия", "выплат")),
    ("Аренда и постоянные", ("аренд", "постоянн", "коммунал", "налог", "интернет", "связь")),
    ("Закупки", ("закупк", "материал", "товар")),
    ("Маркетинг", ("реклам", "маркетинг")),
)
БЕЗ_СТАТЬИ = "Без статьи"


def _f(x: Decimal | None) -> float | None:
    return None if x is None else float(round(x, 2))


def _группа(title: str) -> str:
    low = title.lower()
    return next((name for name, words in ГРУППЫ if any(w in low for w in words)), "Прочее")


def _статья(t: dict) -> str:
    e = t.get("expense")
    if isinstance(e, dict):
        return str(e.get("title") or "").strip() or БЕЗ_СТАТЬИ
    return f"Статья №{e}" if e else БЕЗ_СТАТЬИ


def _день(t: dict) -> date | None:
    try:
        return date.fromisoformat(str(t.get("date") or "")[:10])
    except ValueError:
        return None


async def _транзакции(first: date, last: date) -> list[dict]:
    from app.api.yclients import YClientsClient

    key = f"finance-analysis:{settings.yclients_company_id}:{first}:{last}"

    async def load() -> list[dict]:
        async with YClientsClient() as client:
            return await bm.pages(client, f"/transactions/{client.company_id}",
                                  first.isoformat(), last.isoformat())

    return await cached(key, load, ttl=300)


def разнести(транзакции: list[dict]) -> tuple[dict, list[dict]]:
    """Движения вне продаж по дням и счетам (со знаком) и список расходов.

    Продажи сюда не входят: их берём из закрытий смены. Всё остальное —
    зарплата, закупки, инкассация, внесения — двигает остаток счёта.
    """
    движения: dict[date, dict[str, Decimal]] = defaultdict(lambda: {"cash": D0, "bank": D0})
    расходы: list[dict] = []
    for t in транзакции:
        if t.get("deleted") or t.get("sold_item_type") in ПРОДАЖИ:
            continue
        день = _день(t)
        if день is None:
            continue
        сумма = bm.money(t.get("amount"))
        касса = bool((t.get("account") or {}).get("is_cash"))
        движения[день]["cash" if касса else "bank"] += сумма
        if сумма < 0:
            title = _статья(t)
            расходы.append({
                "date": день, "title": title, "amount": -сумма, "cash": касса,
                # Без категории — то же системное движение денег, что и
                # «перевод»/«инкасс»: решение владельца 05.10.2026, сверено с
                # отчётом «Расходы» в самом YCLIENTS — он такие операции не
                # считает тратой (у инкассации там просто не задана статья).
                "transfer": title == БЕЗ_СТАТЬИ or any(w in title.lower() for w in ПЕРЕВОДЫ),
                "comment": str(t.get("comment") or "")[:80],
            })
    return dict(движения), расходы


async def _закрытия(session: AsyncSession, first: date, last: date) -> dict[date, dict[str, Decimal]]:
    res = await session.execute(
        select(Shift).where(Shift.shift_date >= first, Shift.shift_date <= last)
    )
    out: dict[date, dict[str, Decimal]] = {}
    for s in res.scalars():
        money = (s.closing_snapshot or {}).get("money") or {}
        if s.closed_at is None or money.get("non_cash") is None or money.get("cash") is None:
            continue
        счёт = money.get("cash_counted")
        out[s.shift_date] = {"non_cash": Decimal(str(money["non_cash"])),
                             "cash": Decimal(str(money["cash"])),
                             "spent": Decimal(str(money.get("spent") or 0)),
                             "cash_counted": None if счёт is None else Decimal(str(счёт))}
    return out


def доход_по_месяцам(транзакции: list[dict], first: date, last: date) -> Decimal:
    """Продажи услуг и товаров по кассе YCLIENTS за период включительно."""
    return sum((bm.money(t.get("amount")) for t in транзакции
                if not t.get("deleted") and t.get("sold_item_type") in ПРОДАЖИ
                and (д := _день(t)) is not None and first <= д <= last), D0)


def расходы_по_статьям(items: list[dict], prev_items: list[dict], продажи: Decimal | None,
                       доход: Decimal | None = None, доход_прошлый: Decimal | None = None) -> dict:
    """Свод расходов месяца: по статьям, группам и «где сокращать».

    У групп — доля от общего дохода месяца и та же доля в прошлом месяце:
    сравнивать рубли нечестно, когда выручка сама гуляет (решение владельца 04.10.2026)."""
    сумма = lambda xs: sum((x["amount"] for x in xs if not x["transfer"]), D0)  # noqa: E731
    total, prev_total = сумма(items), сумма(prev_items)
    by: dict[str, dict] = {}
    for x in items:
        if x["transfer"]:
            continue
        a = by.setdefault(x["title"], {"title": x["title"], "total": D0, "count": 0, "cash": D0})
        a["total"] += x["amount"]
        a["count"] += 1
        a["cash"] += x["amount"] if x["cash"] else D0
    prev_by: dict[str, Decimal] = defaultdict(lambda: D0)
    for x in prev_items:
        if not x["transfer"]:
            prev_by[x["title"]] += x["amount"]

    articles = []
    for a in sorted(by.values(), key=lambda a: -a["total"]):
        prev = prev_by.get(a["title"])
        delta = (float(round((a["total"] - prev) / prev * 100, 1)) if prev else None)
        articles.append({
            "title": a["title"], "group": _группа(a["title"]), "total": _f(a["total"]),
            "share_pct": _f(a["total"] / total * 100) if total else None,
            "count": a["count"], "prev_total": _f(prev) if prev is not None else None,
            "delta_pct": delta,
        })

    groups: dict[str, Decimal] = defaultdict(lambda: D0)
    for a in by.values():
        groups[_группа(a["title"])] += a["total"]
    prev_groups: dict[str, Decimal] = defaultdict(lambda: D0)
    for title, v in prev_by.items():
        prev_groups[_группа(title)] += v

    def от_дохода(v: Decimal, база: Decimal | None) -> float | None:
        return _f(v / база * 100) if база else None

    group_rows = []
    for n, v in sorted(groups.items(), key=lambda kv: -kv[1]):
        сейчас = от_дохода(v, доход)
        было = от_дохода(prev_groups.get(n, D0), доход_прошлый) if prev_items else None
        group_rows.append({
            "name": n, "total": _f(v), "share_pct": _f(v / total * 100) if total else None,
            "pct_of_income": сейчас, "prev_pct_of_income": было,
            "delta_pp": round(сейчас - было, 1) if сейчас is not None and было is not None else None,
        })

    watch: list[str] = []
    for a in articles:
        if (a["share_pct"] or 0) >= 5 and a["delta_pct"] is not None and a["delta_pct"] >= 30:
            watch.append(f"«{a['title']}» выросла на {a['delta_pct']:.0f}% к прошлому месяцу "
                         f"({a['total']:,.0f} ₽)".replace(",", " "))
    без_статьи = sum((x["amount"] for x in items if x["title"] == БЕЗ_СТАТЬИ), D0)
    if без_статьи:
        watch.append(f"Расходы без статьи на {float(без_статьи):,.0f} ₽ не входят в сумму "
                     "выше (как инкассация и переводы) — подпишите статью в YCLIENTS, "
                     "если это не так.".replace(",", " "))
    прочее = groups.get("Прочее", D0)
    if total and прочее / total >= Decimal("0.15"):
        watch.append(f"Группа «Прочее» — {float(прочее / total * 100):.0f}% расходов: "
                     "разнесите по понятным статьям.")

    return {
        "total": _f(total), "prev_total": _f(prev_total) if prev_items else None,
        "delta_pct": float(round((total - prev_total) / prev_total * 100, 1)) if prev_total else None,
        "pct_of_sales": _f(total / продажи * 100) if продажи else None,
        "cash": _f(sum((x["amount"] for x in items if x["cash"] and not x["transfer"]), D0)),
        "bank": _f(sum((x["amount"] for x in items if not x["cash"] and not x["transfer"]), D0)),
        "transfers": _f(sum((x["amount"] for x in items if x["transfer"]), D0)),
        "articles": articles, "groups": group_rows, "watch": watch[:4],
        "income": _f(доход) if доход is not None else None,
        "expenses_pct_of_income": _f(total / доход * 100) if доход else None,
    }


async def build(session: AsyncSession, ym: str, today: date | None = None) -> dict[str, Any]:
    today = today or datetime.now(MOSCOW).date()
    m_start, m_end = parse_month(ym)
    month_first, month_last = m_start.date(), min(m_end.date() - timedelta(days=1), today)
    prev_first = parse_month(prev_month(ym))[0].date()
    warnings: list[str] = []

    остатки = await cash_balances.получить(session)
    # Сегодняшний день входит в расчёт только когда смена закрыта.
    закрытия = await _закрытия(session, min(prev_first, month_first), today)
    upto = today if today in закрытия else today - timedelta(days=1)

    база_с = None
    if остатки is not None:
        база_с = min(остатки.cash_as_of, остатки.settlement_as_of) + timedelta(days=1)
    first = min(prev_first, база_с) if база_с else prev_first
    last = max(month_last, upto) if upto >= first else month_last

    движения, расходы = {}, []
    транзакции: list[dict] = []
    expenses_ok = True
    try:
        транзакции = await _транзакции(first, last)
        движения, расходы = разнести(транзакции)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"финансы: транзакции YCLIENTS недоступны: {exc}")
        expenses_ok = False
        warnings.append("Расходы и движения денег YCLIENTS недоступны: расчёт остатков и расходов "
                        "пропущен, повторите обновление.")

    банк = await acquiring.по_дням(session, min(prev_first, база_с or prev_first), last)

    # ── Остатки ──
    balances: dict[str, Any] = {"entered": остатки is not None, "upto": upto.isoformat()}
    debt = {"amount": None, "note": None, "updated_at": None}
    if остатки is not None:
        debt = {"amount": float(остатки.other_account_debt), "note": остатки.other_debt_note,
                "updated_at": остатки.updated_at.isoformat() if остатки.updated_at else None}
        def остаток(старт: Decimal, as_of: date, ключ: str, продажи: str) -> Decimal:
            итог, d = старт, as_of + timedelta(days=1)
            while d <= upto:
                итог += закрытия.get(d, {}).get(продажи, D0) + движения.get(d, {}).get(ключ, D0)
                d += timedelta(days=1)
            return итог

        касса = остаток(остатки.cash_amount, остатки.cash_as_of, "cash", "cash")
        рс = остаток(остатки.settlement_amount, остатки.settlement_as_of, "bank", "non_cash")
        # Поправка на банк: там, где есть отчёт, вместо безнала по смене берём зачисление банка.
        поправка, дней, d = D0, 0, остатки.settlement_as_of + timedelta(days=1)
        while d <= upto:
            if d in банк and d in закрытия:
                поправка += банк[d]["net"] - закрытия[d]["non_cash"]
                дней += 1
            d += timedelta(days=1)
        пропущены = [d.isoformat() for d in (
            (min(остатки.cash_as_of, остатки.settlement_as_of) + timedelta(days=n))
            for n in range(1, (upto - min(остатки.cash_as_of, остатки.settlement_as_of)).days + 1))
            if d not in закрытия][:62]
        balances.update({
            "cash": {"baseline": float(остатки.cash_amount), "as_of": остатки.cash_as_of.isoformat(),
                     "calc": _f(касса) if expenses_ok else None},
            "rs": {"baseline": float(остатки.settlement_amount),
                   "as_of": остатки.settlement_as_of.isoformat(),
                   "calc_yclients": _f(рс) if expenses_ok else None,
                   "calc_bank": _f(рс + поправка) if expenses_ok and дней else None,
                   "bank_days": дней},
            "missing_closure_days": пропущены,
        })
        if пропущены:
            warnings.append(f"Нет закрытой смены за {len(пропущены)} дн. после внесённых остатков: "
                            "остатки посчитаны без этих дней.")

    # ── Месяц по дням ──
    days, итог = [], {k: D0 for k in ("non_cash", "cash", "bank", "fee", "bank_net")}
    d = month_first
    while d <= month_last:
        c, b = закрытия.get(d), банк.get(d)
        diff = (b["amount"] - c["non_cash"]) if b and c else None
        факт = c["cash_counted"] if c else None
        cash_diff = (факт - c["cash"]) if факт is not None else None
        if c is None and b is None:
            status = "pending" if d >= today else "no_data"
        elif c is None:
            status = "no_shift"
        elif b is None:
            status = "no_bank"
        else:
            status = "ok" if abs(diff) <= ДОПУСК else "mismatch"
        if cash_diff is not None and abs(cash_diff) > ДОПУСК:
            status = "mismatch"
        days.append({"date": d.isoformat(), "non_cash": _f(c["non_cash"]) if c else None,
                     "cash": _f(c["cash"]) if c else None,
                     "bank": _f(b["amount"]) if b else None, "diff": _f(diff),
                     "cash_fact": _f(факт), "cash_diff": _f(cash_diff), "status": status})
        if c:
            итог["non_cash"] += c["non_cash"]
            итог["cash"] += c["cash"]
        if b:
            итог["bank"] += b["amount"]
            итог["fee"] += b["fee"]
            итог["bank_net"] += b["net"]
        d += timedelta(days=1)

    сравнимые = [x for x in days if x["diff"] is not None]
    month_totals = {
        "non_cash_shift": _f(итог["non_cash"]), "cash_shift": _f(итог["cash"]),
        "bank_turnover": _f(итог["bank"]) if банк else None,
        "bank_fee": _f(итог["fee"]) if банк else None, "bank_net": _f(итог["bank_net"]) if банк else None,
        "compared_days": len(сравнимые), "mismatch_days": sum(1 for x in days if x["status"] == "mismatch"),
        "diff_total": _f(sum((Decimal(str(x["diff"])) for x in сравнимые), D0)) if сравнимые else None,
        "sales_total": _f(итог["non_cash"] + итог["cash"]),
    }
    if not банк:
        warnings.append("Отчёты банка по эквайрингу ещё не загружены: сверка безнала с банком недоступна.")

    # ── Расходы ──
    в_месяце = [x for x in расходы if month_first <= x["date"] <= month_last]
    в_прошлом = [x for x in расходы if prev_first <= x["date"] < month_first]
    продажи = итог["non_cash"] + итог["cash"]
    expenses = (расходы_по_статьям(
        в_месяце, в_прошлом, продажи or None,
        доход_по_месяцам(транзакции, month_first, month_last),
        доход_по_месяцам(транзакции, prev_first, month_first - timedelta(days=1)),
    ) if expenses_ok else None)
    if expenses and any(a["title"] == БЕЗ_СТАТЬИ for a in expenses["articles"]):
        warnings.append("У части расходов YCLIENTS не прислал статью: они показаны как «Без статьи».")

    return {"month": ym, "today": today.isoformat(), "balances": balances, "debt": debt,
            "totals": month_totals, "days": days, "expenses": expenses, "warnings": warnings,
            "generated_at": datetime.now(MOSCOW).isoformat()}
