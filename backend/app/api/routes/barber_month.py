"""Статистика барберов за месяц и расчёт зарплаты.

Два представления одних и тех же данных. В статистике записей зарплата не
появляется вовсе. В расчёте зарплаты мастер видит только свою строку — отбор
делается здесь, на сервере: прятать чужие деньги на стороне браузера значит
не прятать их вообще.
"""

from decimal import Decimal

from fastapi import APIRouter, HTTPException, Request

from app.main_roles import ROLE_MASTER, ROLE_OPERATOR, ROLE_OWNER
from app.services.barber_month import report

router = APIRouter(prefix="/api/barbers", tags=["barbers"])

# Поля, которых не должно быть в статистике записей: она про загрузку мастеров,
# а не про их доход.
SALARY_FIELDS = ("rule", "earned", "forecast", "days")

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

    видимые = [{k: v for k, v in m.items() if k not in SALARY_FIELDS} for m in masters]
    result["masters"] = [{**m, **_expected(m)} for m in видимые]

    # Итог считается по тем строкам, что показаны: мастер видит свою строку, и
    # итог под ней должен совпадать с ней, а не с суммой по всему салону.
    итог = {k: v for k, v in _totals(masters).items() if k not in ("earned", "forecast")}

    # _totals складывает столбец, пропуская неизвестные значения, и по косметике
    # отдаёт ноль вместо «неизвестно». Для прогноза это разные вещи: ноль он
    # сложит как настоящую сумму. Поэтому если хоть у одного мастера косметика
    # не получена, в итоге её тоже нет.
    if any(m.get("product_sales") is None for m in видимые):
        итог["product_sales"] = None

    result["totals"] = {**итог, **_expected(итог)}
    result["scope"] = "own" if role == ROLE_MASTER else "all"

    result["warnings"] = [w for w in result["warnings"] if "косметики" in w]
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
