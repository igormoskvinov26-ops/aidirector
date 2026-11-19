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

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.models import PlanTarget
from app.services import acquiring
from app.services import barber_month as bm
from app.services.cache import cached
from app.services.finance_analysis import (
    БЕЗ_СТАТЬИ,
    ПЕРЕВОДЫ,
    ПРОДАЖИ,
    _день,
    _группа,
    _закрытия,
    _статья,
    _f,
)
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
            if статья == БЕЗ_СТАТЬИ or any(w in статья.lower() for w in ПЕРЕВОДЫ):
                # Без категории — то же самое системное движение денег, что и
                # «перевод»/«инкасс»: YCLIENTS в собственном отчёте «Расходы»
                # такие операции не считает тратой (решение владельца 05.10.2026,
                # проверено сверкой с отчётом YCLIENTS — расхождение было ровно
                # на сумму операций без статьи).
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


def прогноз_месяца(
    по_месяцам: dict[str, dict], today: date, записано_вперёд: Decimal | None,
) -> dict[str, Any]:
    """Прогноз на конец месяца: выручка, ФОТ, прочие расходы (решение владельца
    19.11.2026). Выручка — по уже существующим записям, без гаданий: факт с
    начала месяца плюс уже стоящее в записи вперёд.

    ФОТ и прочие расходы из месяца в месяц почти не меняются, поэтому вместо
    линейной экстраполяции темпа берём историю за БЮДЖЕТ_ПО месяцев:
      * ФОТ — почти всегда одна и та же доля от дохода (аренда выручки не
        знает, а комиссия мастеров — знает), поэтому прогнозируем его как
        % от прогноза выручки, а не абсолютной суммой;
      * прочие расходы (аренда, коммуналка, закупки, маркетинг) — наоборот,
        от выручки не зависят, поэтому берём их среднюю абсолютную сумму.
    """
    месяцы = sorted(по_месяцам)
    текущий = месяцы[-1]
    прошлые = [по_месяцам[m] for m in месяцы[:-1][-БЮДЖЕТ_ПО:] if по_месяцам[m]["expenses"] > 0]

    доли_фот = [м["groups"].get("ФОТ", D0) / м["income"] for м in прошлые if м["income"] > 0]
    доля_фот = (sum(доли_фот, D0) / len(доли_фот)) if доли_фот else None

    прочие_суммы = [м["expenses"] - м["groups"].get("ФОТ", D0) for м in прошлые]
    прочие = (sum(прочие_суммы, D0) / len(прочие_суммы)) if прочие_суммы else None

    выручка = (по_месяцам[текущий]["income"] + записано_вперёд) if записано_вперёд is not None else None
    фот = (выручка * доля_фот) if выручка is not None and доля_фот is not None else None
    прибыль = (выручка - фот - прочие) if None not in (выручка, фот, прочие) else None

    return {
        "revenue": _f(выручка), "payroll": _f(фот), "other_expenses": _f(прочие), "profit": _f(прибыль),
        "payroll_pct_of_revenue": _f(доля_фот * 100) if доля_фот is not None else None,
        "months_used": len(прошлые),
    }


КОНТРОЛЬНЫЕ_ТОЧКИ = (
    (10, "Выплата ЗП"),
    (25, "Аванс, аренда и коммуналка"),
)


def _доход_по_дням(транзакции: list[dict]) -> dict[date, Decimal]:
    по_дням: dict[date, Decimal] = defaultdict(lambda: D0)
    for t in транзакции:
        if t.get("deleted") or t.get("sold_item_type") not in ПРОДАЖИ:
            continue
        д = _день(t)
        if д is not None:
            по_дням[д] += bm.money(t.get("amount"))
    return dict(по_дням)


def контрольные_точки(
    транзакции_месяца: list[dict], вперёд_по_дням: dict[date, Decimal] | None, today: date,
) -> list[dict[str, Any]]:
    """Выручка на даты выплат внутри месяца (решение владельца 19.11.2026):
    10-е — зарплата, 25-е — аванс, аренда и коммуналка. Прошедшая дата — факт
    по кассе день-в-день, будущая — факт на сегодня плюс то, что уже стоит в
    записи до этой даты. Последний день месяца сюда не входит — там уже есть
    прогноз_месяца() целиком на весь месяц (итоги, дивиденды).
    """
    по_дням = _доход_по_дням(транзакции_месяца)
    точки = []
    for день, подпись in КОНТРОЛЬНЫЕ_ТОЧКИ:
        дата = date(today.year, today.month, день)
        if дата <= today:
            выручка = sum((v for d, v in по_дням.items() if d <= дата), D0)
        elif вперёд_по_дням is None:
            выручка = None
        else:
            выручка = (
                sum((v for d, v in по_дням.items() if d <= today), D0)
                + sum((v for d, v in вперёд_по_дням.items() if today < d <= дата), D0)
            )
        точки.append({
            "date": дата.isoformat(), "label": подпись,
            "revenue": _f(выручка) if выручка is not None else None,
            "passed": дата <= today,
        })
    return точки


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


async def _вперёд_по_дням(today: date) -> dict[date, Decimal]:
    key = f"owner-overview-booked-days:{settings.yclients_company_id}:{today.isoformat()}"

    async def load() -> dict[date, Decimal]:
        from app.api.yclients import YClientsClient

        async with YClientsClient() as client:
            return await bm.future_booked_by_day(client, datetime.now(MOSCOW))

    # То же окно, что и у текущего месяца в итогах: 5 минут.
    return await cached(key, load, ttl=300)


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
    текущий_ym = today.strftime("%Y-%m")
    транзакции_по_месяцам = {ym: await _транзакции_месяца(ym, today) for ym in _месяцы(today)}
    по_месяцам = {ym: итоги_месяца(t) for ym, t in транзакции_по_месяцам.items()}
    план = await session.scalar(select(PlanTarget).where(PlanTarget.period == текущий_ym))
    итог = свести(по_месяцам, Decimal(str(план.profit_target)) if план else D0, today)
    итог["recon"] = await сверка_месяца(session, today)

    записано_вперёд, вперёд_по_дням = None, None
    try:
        вперёд_по_дням = await _вперёд_по_дням(today)
        записано_вперёд = sum(вперёд_по_дням.values(), D0)
        итог["booked_until_month_end"] = _f(записано_вперёд)
    except Exception as e:  # noqa: BLE001 — YCLIENTS может быть недоступен
        logger.warning(f"owner_overview: записано вперёд не посчиталось: {e}")
        итог["booked_until_month_end"] = None

    итог["forecast"] = прогноз_месяца(по_месяцам, today, записано_вперёд)
    итог["forecast"]["checkpoints"] = контрольные_точки(
        транзакции_по_месяцам[текущий_ym], вперёд_по_дням, today
    )
    return итог
