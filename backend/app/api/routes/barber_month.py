"""Статистика барберов за месяц и расчёт зарплаты.

Два представления одних и тех же данных. В статистике записей зарплата не
появляется вовсе. В расчёте зарплаты мастер видит только свою строку — отбор
делается здесь, на сервере: прятать чужие деньги на стороне браузера значит
не прятать их вообще.
"""

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.main_roles import ROLE_MASTER, ROLE_OPERATOR, ROLE_OWNER
from app.services import finance
from app.services.barber_month import report

router = APIRouter(prefix="/api/barbers", tags=["barbers"])

# Что не уходит в дашборд месяца. Условия оплаты, прогноз зарплаты и разбивка
# по дням — это уже расчёт ЗП, у него своя вкладка.
#
# Начисленная зарплата (earned) отсюда убрана намеренно: по просьбе владельца
# 18.09.2026 дашборд показывает не только выручку мастера, но и то, что от неё
# остаётся салону. Без зарплаты такой столбец не посчитать.
#
# Разграничение прав от этого не меняется: мастер по-прежнему видит только
# свою строку, отбор идёт ниже по staff_id.
СЛУЖЕБНЫЕ_ПОЛЯ = ("rule", "forecast", "days")

# Кому видны все мастера и общий итог.
ROLES_SEEING_EVERYONE = (ROLE_OWNER, ROLE_OPERATOR)


async def _safe_report() -> dict:
    try:
        return await report()
    except Exception as exc:
        raise HTTPException(
            502, "Не удалось получить полные данные YCLIENTS. Повторите обновление."
        ) from exc


def _only_own(masters: list[dict], staff_id: int | None) -> list[dict]:
    """Оставить строку одного мастера. Без привязки не показывать ничего."""
    if staff_id is None:
        return []
    return [m for m in masters if int(m["staff_id"]) == staff_id]


def _вклад(строка: dict) -> dict:
    """Сколько мастер принёс салону к текущему моменту.

    Принесено = выручка мастера минус его начисленная зарплата. Выручка — это
    услуги выполненных записей и проданная косметика, то есть деньги, которые
    уже в кассе; будущие записи сюда не входят, их ещё не оплатили.

    Это НЕ чистая прибыль салона, и называть её так нельзя. Постоянные расходы
    — 389 117 ₽ в месяц, — расходники и эквайринг сюда не входят: они не
    делятся по мастерам. Сложив три этих числа и сравнив с планом по прибыли,
    владелец решит, что до плана ближе, чем на самом деле.

    Если зарплата не посчитана (YCLIENTS не отдал график или продажи), вклад
    не считается вовсе. Выручка без вычета зарплаты выглядела бы как вклад и
    завышала бы его на десятки тысяч.
    """
    зарплата = строка.get("earned")
    косметика = строка.get("product_sales")
    if зарплата is None or косметика is None:
        return {"payroll": None if зарплата is None else float(зарплата),
                "contribution": None}

    выручка = Decimal(str(строка.get("completed_revenue") or 0)) + Decimal(str(косметика))
    return {
        "payroll": float(зарплата),
        "contribution": float(выручка - Decimal(str(зарплата))),
    }


def _expected(строка: dict) -> dict:
    """Прогноз по мастеру: выполненное плюс будущее. Три величины.

    * expected_count — сколько записей выйдет за месяц;
    * expected_services — только услуги: выполненные плюс будущие;
    * expected_revenue — то же вместе с проданной косметикой.

    Две суммы, а не одна, по решению владельца 17.09.2026. Разделение полезно
    вдвойне. Услуги — это то, чем мастер управляет своим расписанием, и
    сравнивать по ним мастеров честнее. А косметика приходит из отдельного
    ответа YCLIENTS, который может и не прийти: столбец услуг считается всегда,
    и без косметики дашборд не становится пустым.

    Когда продажи косметики недоступны, expected_revenue не считается вовсе.
    Неполная сумма выглядит как полная: увидев её, владелец решит, что до плана
    не хватает больше, чем на самом деле. Причина при этом уже лежит в
    warnings — там сказано, что продажи не получены.
    """
    записей = int(строка.get("completed_count") or 0) + int(строка.get("future_count") or 0)
    услуги = Decimal(str(строка.get("completed_revenue") or 0)) + Decimal(
        str(строка.get("future_revenue") or 0)
    )

    косметика = строка.get("product_sales")
    с_косметикой = None if косметика is None else float(услуги + Decimal(str(косметика)))

    return {
        "expected_count": записей,
        "expected_services": float(услуги),
        "expected_revenue": с_косметикой,
    }


def _totals(masters: list[dict]) -> dict:
    """Итог по всем мастерам. Считается по тем же строкам, что показаны."""
    def _sum(key: str) -> Decimal:
        return sum(
            (Decimal(str(m[key])) for m in masters if m.get(key) is not None),
            Decimal("0"),
        )

    # Если хоть у кого-то зарплата не посчитана, итог по ней не складываем:
    # неполная сумма выглядит как полная и вводит в заблуждение.
    salary_known = masters and all(m.get("earned") is not None for m in masters)

    return {
        "completed_count": int(_sum("completed_count")),
        "completed_revenue": float(_sum("completed_revenue")),
        "future_count": int(_sum("future_count")),
        "future_revenue": float(_sum("future_revenue")),
        "product_sales": float(_sum("product_sales")),
        "earned": float(_sum("earned")) if salary_known else None,
        "forecast": float(_sum("forecast")) if salary_known else None,
    }


@router.get("/future")
async def future(request: Request) -> dict:
    """Месяц по мастерам: выполнено, впереди, прогноз.

    Строки — мастера, плюс итог по всем. Столбцы — три величины по выполненным
    записям (количество, услуги, косметика), две по будущим (количество, сумма)
    и три прогнозные: записей, услуги, услуги вместе с косметикой.

    Зарплаты здесь нет и быть не должно: это загрузка мастеров, а не их доход.
    Доход — в расчёте ЗП, и там своё разграничение прав.
    """
    result = await _safe_report()
    role = getattr(request.state, "role", ROLE_MASTER)

    masters = result["masters"]
    if role == ROLE_MASTER:
        masters = _only_own(masters, getattr(request.state, "staff_id", None))

    видимые = [{k: v for k, v in m.items() if k not in СЛУЖЕБНЫЕ_ПОЛЯ} for m in masters]
    строки = [{**m, **_expected(m), **_вклад(m)} for m in видимые]

    # Порядок — по прогнозу выручки с косметикой, от большего. Это то число,
    # ради которого владелец открывает страницу, и сравнивать мастеров он
    # будет по нему. Алфавит или порядок в настройках тут ничего не говорят.
    #
    # Когда прогноз с косметикой неизвестен, сортируем по услугам: они есть
    # всегда. Иначе строка без косметики улетала бы в конец таблицы, хотя
    # мастер мог заработать больше всех.
    строки.sort(
        key=lambda м: float(
            м.get("expected_revenue")
            if м.get("expected_revenue") is not None
            else (м.get("expected_services") or 0)
        ),
        reverse=True,
    )
    result["masters"] = строки

    # Итог считается по тем строкам, что показаны: мастер видит свою строку, и
    # итог под ней должен совпадать с ней, а не с суммой по всему салону.
    итог = {k: v for k, v in _totals(masters).items() if k not in ("earned", "forecast")}

    # _totals складывает столбец, пропуская неизвестные значения, и по косметике
    # отдаёт ноль вместо «неизвестно». Для прогноза это разные вещи: ноль он
    # сложит как настоящую сумму. Поэтому если хоть у одного мастера косметика
    # не получена, в итоге её тоже нет.
    if any(m.get("product_sales") is None for m in видимые):
        итог["product_sales"] = None

    # Зарплата в итоге складывается по тем же правилам, что и остальное: если
    # хоть у одного мастера она не посчитана, итог по ней не показывается.
    # Неполная сумма выглядит как полная.
    if any(m.get("earned") is None for m in видимые):
        итог["earned"] = None
    else:
        итог["earned"] = float(sum(Decimal(str(m["earned"])) for m in видимые))

    result["totals"] = {**итог, **_expected(итог), **_вклад(итог)}
    result["scope"] = "own" if role == ROLE_MASTER else "all"

    # Продажи не через мастеров (администраторы) — отдельная сводка, не
    # строка в таблице выше: у неё нет ни расписания, ни прогноза, ни
    # зарплаты, это просто деньги, которые иначе никуда бы не попали.
    # Мастеру своя очередь чужая выручка не нужна — как и остальной салон,
    # она видна только тому, кто видит весь салон.
    admin_sales = result.pop("admin_sales", None)

    company_revenue = None
    if role != ROLE_MASTER and admin_sales is not None:
        result["admin_sales"] = admin_sales

        # «Прибыль» на этой странице должна быть выручкой всего салона, а не
        # только трёх зарегистрированных барберов — иначе в неё не попадают
        # деньги вроде продажи администратора. Отдельное поле, а не правка
        # totals.expected_revenue: строка «Итого по мастерам» обязана совпадать
        # с суммой видимых строк, это проверяется взглядом на таблицу.
        barbers_revenue = result["totals"].get("expected_revenue")
        admin_totals = admin_sales["totals"]
        if barbers_revenue is not None and admin_totals.get("product_sales") is not None:
            company_revenue = float(
                Decimal(str(barbers_revenue))
                + Decimal(str(admin_totals["completed_revenue"]))
                + Decimal(str(admin_totals["product_sales"]))
            )
    result["totals"]["company_revenue"] = company_revenue

    result["warnings"] = [
        w for w in result["warnings"] if "косметики" in w or "администраторов" in w
    ]
    return result


@router.get("/payroll")
async def payroll(request: Request) -> dict:
    """Расчёт зарплаты. Мастер видит себя, владелец и администратор — всех."""
    result = await _safe_report()
    role = getattr(request.state, "role", ROLE_MASTER)

    if role in ROLES_SEEING_EVERYONE:
        result["totals"] = _totals(result["masters"])
        result["scope"] = "all"
        return result

    result["masters"] = _only_own(result["masters"], getattr(request.state, "staff_id", None))
    result["scope"] = "own"
    return result


@router.get("/return-rate")
async def return_rate(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    """Возвращаемость мастеров: доля клиентов, пришедших повторно к тому же.

    В отличие от /future и /payroll, считается по локальной базе, а не
    живым опросом YCLIENTS: это история за год, а не за месяц, и таскать
    её на каждое открытие страницы было бы медленно. Подробности расчёта —
    в app/services/finance.py:get_return_rate.

    Мастеру чужая возвращаемость не нужна — как и остальной салон, эта
    сводка видна только тому, кто видит весь салон.
    """
    if getattr(request.state, "role", ROLE_MASTER) == ROLE_MASTER:
        raise HTTPException(403, "Раздел доступен только владельцу")
    return await finance.get_return_rate(db)
