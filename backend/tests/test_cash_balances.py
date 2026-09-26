"""Остатки в кассе и на счёте: хранение и подстановка в блок «Деньги».

Решение владельца 26.09.2026. Регистр день-за-днём YCLIENTS вести нельзя без
подтверждённых полей нал/безнал и признака расхода (§39 ТЗ смены) — здесь
проверяется только честная часть: сохранённый остаток показывается с датой,
на которую он известен, и не выдаётся за пересчитанный, если день ушёл
вперёд.
"""

from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.requests import Request

from app.api.routes.shift import _require_owner
from app.database import Base
from app.main_roles import ROLE_MASTER, ROLE_OPERATOR, ROLE_OWNER
from app.services import cash_balances

ДЕНЬ = date(2026, 9, 26)


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_без_внесённых_остатков_всё_недоступно(session: AsyncSession):
    assert await cash_balances.получить(session) is None
    assert await cash_balances.как_словарь(session) is None

    добавка = cash_balances.в_блок_денег(None, ДЕНЬ)
    assert добавка == {
        "cash_register_estimate": None,
        "settlement_account_estimate": None,
        "other_account_debt": None,
        "warning": None,
    }


@pytest.mark.asyncio
async def test_сохранить_и_прочитать(session: AsyncSession):
    итог = await cash_balances.сохранить(
        session,
        cash_amount=Decimal("7446"),
        cash_as_of=ДЕНЬ,
        settlement_amount=Decimal("0"),
        settlement_as_of=ДЕНЬ,
        other_account_debt=Decimal("40000"),
        other_debt_note="заняли на расходы бизнеса",
    )
    assert итог["cash_amount"] == 7446.0
    assert итог["cash_as_of"] == "2026-09-26"
    assert итог["other_account_debt"] == 40000.0

    из_базы = await cash_balances.как_словарь(session)
    assert из_базы == итог


@pytest.mark.asyncio
async def test_повторное_сохранение_затирает_старое_а_не_копит(session: AsyncSession):
    await cash_balances.сохранить(
        session, cash_amount=Decimal("100"), cash_as_of=ДЕНЬ,
        settlement_amount=Decimal("0"), settlement_as_of=ДЕНЬ,
        other_account_debt=Decimal("0"), other_debt_note=None,
    )
    await cash_balances.сохранить(
        session, cash_amount=Decimal("200"), cash_as_of=ДЕНЬ,
        settlement_amount=Decimal("0"), settlement_as_of=ДЕНЬ,
        other_account_debt=Decimal("0"), other_debt_note=None,
    )
    итог = await cash_balances.как_словарь(session)
    assert итог["cash_amount"] == 200.0


def test_в_блок_денег_без_предупреждения_когда_день_совпадает():
    from app.models.models import CashBalances

    остатки = CashBalances(
        id=1, cash_amount=Decimal("7446"), cash_as_of=ДЕНЬ,
        settlement_amount=Decimal("0"), settlement_as_of=ДЕНЬ,
        other_account_debt=Decimal("40000"), other_debt_note=None,
    )
    добавка = cash_balances.в_блок_денег(остатки, ДЕНЬ)
    assert добавка["cash_register_estimate"] == 7446.0
    assert добавка["other_account_debt"] == 40000.0
    assert добавка["warning"] is None


def test_в_блок_денег_предупреждает_когда_день_ушёл_вперёд():
    from datetime import timedelta

    from app.models.models import CashBalances

    остатки = CashBalances(
        id=1, cash_amount=Decimal("7446"), cash_as_of=ДЕНЬ,
        settlement_amount=Decimal("0"), settlement_as_of=ДЕНЬ,
        other_account_debt=Decimal("40000"), other_debt_note=None,
    )
    добавка = cash_balances.в_блок_денег(остатки, ДЕНЬ + timedelta(days=3))
    assert добавка["cash_register_estimate"] == 7446.0  # показан, не обнулён
    assert "касса" in добавка["warning"]
    assert "счёт" in добавка["warning"]


# --------------------------------------------------------------------------- #
# Раздел доступен только владельцу
# --------------------------------------------------------------------------- #


def _fake_request(role: str) -> Request:
    request = Request({"type": "http", "headers": []})
    request.state.role = role
    return request


def test_владельцу_можно():
    _require_owner(_fake_request(ROLE_OWNER))  # не должно бросить исключение


@pytest.mark.parametrize("role", [ROLE_OPERATOR, ROLE_MASTER])
def test_остальным_нельзя(role):
    with pytest.raises(HTTPException) as ошибка:
        _require_owner(_fake_request(role))
    assert ошибка.value.status_code == 403
