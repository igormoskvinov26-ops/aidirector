"""Остатки в кассе и на расчётном счёте — единственная строка настроек.

Решение владельца 26.09.2026. Пока YCLIENTS не отдаёт подтверждённых полей
нал/безнал и признака расхода (§39 ТЗ смены), вести день-за-днём регистр
нельзя — храним известный остаток на дату as_of и показываем его с этой
датой, а не пересчитываем молча вперёд. Долг перед другим счётом YCLIENTS
вообще не видит: занимали на расходы бизнеса с личного/стороннего счёта,
это исключительно ручная цифра.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import CashBalances

# Единственная строка. Не по дате и не по владельцу: остаток один на весь
# салон, отдельного смысла заводить несколько строк нет.
ID = 1


async def получить(session: AsyncSession) -> CashBalances | None:
    строка = await session.execute(select(CashBalances).where(CashBalances.id == ID))
    return строка.scalars().first()


async def как_словарь(session: AsyncSession) -> dict | None:
    """Для GET и для подстановки в блок «Деньги». None — ещё не заводили."""
    остатки = await получить(session)
    if остатки is None:
        return None
    return {
        "cash_amount": float(остатки.cash_amount),
        "cash_as_of": остатки.cash_as_of.isoformat(),
        "settlement_amount": float(остатки.settlement_amount),
        "settlement_as_of": остатки.settlement_as_of.isoformat(),
        "other_account_debt": float(остатки.other_account_debt),
        "other_debt_note": остатки.other_debt_note,
        "updated_at": остатки.updated_at.isoformat(),
    }


async def сохранить(
    session: AsyncSession,
    *,
    cash_amount: Decimal,
    cash_as_of: date,
    settlement_amount: Decimal,
    settlement_as_of: date,
    other_account_debt: Decimal,
    other_debt_note: str | None,
) -> dict:
    """Владелец вносит остатки заново.

    Цифра целиком ручная: значение по умолчанию задним числом не
    подставляется, старое затирается новым без попытки его пересчитать.
    """
    остатки = await получить(session)
    if остатки is None:
        остатки = CashBalances(id=ID)
        session.add(остатки)
    остатки.cash_amount = cash_amount
    остатки.cash_as_of = cash_as_of
    остатки.settlement_amount = settlement_amount
    остатки.settlement_as_of = settlement_as_of
    остатки.other_account_debt = other_account_debt
    остатки.other_debt_note = other_debt_note
    await session.commit()
    return await как_словарь(session)


def в_блок_денег(остатки: CashBalances | None, день: date) -> dict:
    """Подставить остатки в money-блок закрытия и предупреждения к ним.

    Показываем сохранённый остаток даже если день ушёл вперёд относительно
    as_of — это уже известный факт, а не ноль. Но явно предупреждаем: он не
    пересчитан на сегодняшние движения, пока не подтверждены поля YCLIENTS.
    """
    if остатки is None:
        return {
            "cash_register_estimate": None,
            "settlement_account_estimate": None,
            "other_account_debt": None,
            "warning": None,
        }

    предупреждения = []
    if остатки.cash_as_of != день:
        предупреждения.append(
            f"касса — на {остатки.cash_as_of.strftime('%d.%m')}, дальше не пересчитана"
        )
    if остатки.settlement_as_of != день:
        предупреждения.append(
            f"счёт — на {остатки.settlement_as_of.strftime('%d.%m')}, дальше не пересчитан"
        )

    предупреждение = (
        "Остатки денег (" + "; ".join(предупреждения) + ")." if предупреждения else None
    )
    return {
        "cash_register_estimate": float(остатки.cash_amount),
        "settlement_account_estimate": float(остатки.settlement_amount),
        "other_account_debt": float(остатки.other_account_debt),
        "warning": предупреждение,
    }
