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
    """Записи за месяц по мастерам: выполнено, впереди, косметика."""
    result = await _safe_report()
    role = getattr(request.state, "role", ROLE_MASTER)

    masters = result["masters"]
    if role == ROLE_MASTER:
        masters = _only_own(masters, getattr(request.state, "staff_id", None))

    result["masters"] = [
        {k: v for k, v in m.items() if k not in SALARY_FIELDS} for m in masters
    ]
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
