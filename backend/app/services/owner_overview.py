"""Страница Владельца «как идут дела»: доход, расходы и прибыль за месяц.

Решения (04.10.2026, ответы по умолчанию, Игорь может поправить):
  * доход и расходы — реальные деньги по кассовым операциям YCLIENTS: продажи
    услуг и товаров — доход, остальные списания (кроме переводов между
    счетами) — расходы. Так три блока сходятся: прибыль = доход − расходы;
  * бюджет расходов — среднее за 3 прошлых полных месяца;
  * план дохода = план прибыли + бюджет расходов (отдельного поля нет);
  * «идём в темпе» — доля выполнения плана против доли прошедшего месяца
    (15-е из 30 дней — 50%).
Закрытия смены ведутся только с конца сентября 2026, поэтому история за
полгода берётся из YCLIENTS, а не из закрытий.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.models import PlanTarget
from app.services import acquiring
from app.services import barber_month as bm
from app.services.cache import cached
from app.services.finance_analysis import ПРОДАЖИ, _закрытия, _f, _день, _группа, _статья, ПЕРЕВОДЫ
from app.services.monthly_report import MOSCOW

МЕСЯЦЕВ = 6
БЮДЖЕТ_ПО = 3  # месяцев для среднего расхода
D0 = Decimal(0)


def _месяцы(today: date, n: int = МЕСЯЦЕВ) -> list[str]:
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        out.append(f"{y}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out[::-1]


def _границы(ym: str) -> tuple[date, date]:
    y, m = map(int, ym.split("-"))
    first = date(y, m, 1)
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return first, nxt - timedelta(days=1)


def итоги_месяца(транзакции: list[dict]) -> dict:
    """Доход, расходы и расходы по группам из кассовых операций месяца."""
    доход, расход = D0, D0
    группы: dict[str, Decimal] = defaultdict(lambda: D0)
    for t in транзакции:
        if t.get("deleted") or _день(t) is None:
            continue
        сумма = bm.money(t.get("amount"))
        if t.get("sold_item_type") in ПРОДАЖИ:
            доход += сумма
        elif сумма < 0:
            статья = _статья(t)
            if any(w in статья.lower() for w in ПЕРЕВОДЫ):
                continue  # деньги переехали между кассой и счётом — не трата
            расход += -сумма
            группы[_группа(статья)] += -сумма
    return {"income": доход, "expenses": расход, "groups": dict(группы)}


def свести(по_месяцам: dict[str, dict], план_прибыли: Decimal, today: date) -> dict[str, Any]:
    """Чистый расчёт страницы по итогам месяцев (последний — текущий)."""
    месяцы = sorted(по_месяцам)
    текущий = месяцы[-1]
    сейчас = по_месяцам[текущий]
    _, последний = _границы(текущий)
    дней = последний.day
    прошло = Decimal(today.day) / Decimal(дней)

    прошлые = [по_месяцам[m]["expenses"] for m in месяцы[:-1][-БЮДЖЕТ_ПО:] if по_месяцам[m]["expenses"] > 0]
    бюджет = (sum(прошлые, D0) / len(прошлые)) if прошлые else None
    план_дохода = (план_прибыли + бюджет) if план_прибыли > 0 and бюджет is not None else None

    доход, расход = сейчас["income"], сейчас["expenses"]
    прибыль = доход - расход

    def доля(часть: Decimal, целое: Decimal | None) -> float | None:
        return float(round(часть / целое * 100, 1)) if целое else None

    доля_дохода = доля(доход, план_дохода)
    доля_расхода = доля(расход, бюджет)
    темп = float(round(прошло * 100, 1))
    темп_прибыли = план_прибыли * прошло if план_прибыли > 0 else None

    группы = sorted(сейчас["groups"].items(), key=lambda kv: -kv[1])
    return {
        "today": today.isoformat(), "month": текущий, "day": today.day, "days_in_month": дней,
        "elapsed_pct": темп,
        "income": {
            "value": _f(доход), "plan": _f(план_дохода), "pct_of_plan": доля_дохода,
            "ok": None if доля_дохода is None else доля_дохода >= темп,
        },
        "expenses": {
            "value": _f(расход), "budget": _f(бюджет), "pct_of_budget": доля_расхода,
            "ok": None if доля_расхода is None else доля_расхода <= темп,
            "groups": [{"name": n, "total": _f(v), "share_pct": доля(v, расход)} for n, v in группы],
        },
        "profit": {
            "value": _f(прибыль), "plan": _f(план_прибыли) if план_прибыли > 0 else None,
            "pace": _f(темп_прибыли),
            "margin_pct": доля(прибыль, доход),
            "ok": (прибыль >= 0) if темп_прибыли is None else (прибыль >= 0 and прибыль >= темп_прибыли),
        },
        "history": [
            {"month": m, "income": _f(по_месяцам[m]["income"]), "expenses": _f(по_месяцам[m]["expenses"]),
             "profit": _f(по_месяцам[m]["income"] - по_месяцам[m]["expenses"]), "partial": m == текущий}
            for m in месяцы
        ],
        "income_plan_basis": "план прибыли + средние расходы за 3 прошлых месяца",
    }


async def _транзакции_месяца(ym: str, today: date) -> list[dict]:
    from app.api.yclients import YClientsClient

    first, last = _границы(ym)
    last = min(last, today)
    текущий = ym == today.strftime("%Y-%m")
    key = f"owner-overview:{settings.yclients_company_id}:{ym}:{last}"

    async def load() -> list[dict]:
        async with YClientsClient() as client:
            return await bm.pages(client, f"/transactions/{client.company_id}",
                                  first.isoformat(), last.isoformat())

    # Прошедшие месяцы не меняются — держим их полдня, текущий — 5 минут.
    return await cached(key, load, ttl=300 if текущий else 6 * 3600)


async def сверка_месяца(session: AsyncSession, today: date) -> dict[str, Any]:
    """Итог сверки за текущий месяц: YCLIENTS против банка и налички в кассе."""
    first, _ = _границы(today.strftime("%Y-%m"))
    закрытия = await _закрытия(session, first, today)
    банк = await acquiring.по_дням(session, first, today)
    разница, сверено, расходятся = D0, 0, 0
    for день, c in закрытия.items():
        b = банк.get(день)
        if b is None:
            continue
        касса = c["cash_counted"] if c.get("cash_counted") is not None else c["cash"]
        d = (b["amount"] + касса) - (c["non_cash"] + c["cash"])
        разница += d
        сверено += 1
        расходятся += abs(d) > 1
    без_банка = sum(1 for д in закрытия if д not in банк)
    return {"diff_total": _f(разница), "compared_days": сверено, "mismatch_days": расходятся,
            "days_without_bank": без_банка}


async def построить(session: AsyncSession, today: date | None = None) -> dict[str, Any]:
    today = today or datetime.now(MOSCOW).date()
    по_месяцам = {ym: итоги_месяца(await _транзакции_месяца(ym, today)) for ym in _месяцы(today)}
    план = await session.scalar(select(PlanTarget).where(PlanTarget.period == today.strftime("%Y-%m")))
    итог = свести(по_месяцам, Decimal(str(план.profit_target)) if план else D0, today)
    итог["recon"] = await сверка_месяца(session, today)
    return итог
