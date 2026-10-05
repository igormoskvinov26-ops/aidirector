"""Обмен через общий сервер: две установки, настоящий код сервера в памяти."""

import importlib.util
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.models import AcquiringRow, AppSetting, Base, CashBalances, Shift, ShiftEmployee
from app.services import hub

HUB_FILE = Path(__file__).resolve().parents[2] / "hub" / "app.py"


def _server(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_TOKEN", "k")
    monkeypatch.setenv("HUB_DB", str(tmp_path / "hub.db"))
    spec = importlib.util.spec_from_file_location("hub_app", HUB_FILE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["hub_app"] = mod
    spec.loader.exec_module(mod)
    return mod.app


async def _install(tmp_path, name):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / name}.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


async def test_две_установки_обмениваются_и_не_гоняют_данные_по_кругу(tmp_path, monkeypatch):
    app = _server(tmp_path, monkeypatch)
    a, b = await _install(tmp_path, "a"), await _install(tmp_path, "b")
    day = date(2026, 10, 4)

    def client():
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://hub",
                                 headers={"Authorization": "Bearer k"})

    async with a() as sa, b() as sb, client() as c:
        sa.add_all([CashBalances(id=1, cash_amount=Decimal("1000"), cash_as_of=day,
                                 settlement_amount=Decimal("5000"), settlement_as_of=day,
                                 other_account_debt=Decimal("40000"), other_debt_note="долг"),
                    AppSetting(key="pulse_start_date", value="2026-10-01"),
                    AcquiringRow(op_date=day, amount=Decimal("6550"), fee=Decimal("79.91"),
                                 net=Decimal("6470.09"), source_file="x.csv")])
        shift = Shift(shift_date=day, closing_snapshot={"money": {"cash": 100}})
        sa.add(shift)
        await sa.flush()
        sa.add(ShiftEmployee(shift_id=shift.id, staff_id=7, staff_name_snapshot="Иван", arrival_time="10:00"))
        await sa.commit()

        first = await hub.обмен(sa, c, day)
        assert first["pushed"] == 4 and first["pulled"] == 0
        got = await hub.обмен(sb, c, day)
        assert got["pulled"] == 4 and got["pushed"] == 0

        assert (await sb.get(CashBalances, 1)).other_account_debt == Decimal("40000.00")
        assert (await sb.execute(select(Shift))).scalars().first().closing_snapshot == {"money": {"cash": 100}}
        assert (await sb.execute(select(ShiftEmployee))).scalars().first().arrival_time == "10:00"
        assert (await sb.execute(select(AcquiringRow))).scalars().first().net == Decimal("6470.09")

        # покой: ничего не отправляется и не забирается
        assert await hub.обмен(sb, c, day) == {"pushed": 0, "pulled": 0}
        assert await hub.обмен(sa, c, day) == {"pushed": 0, "pulled": 0}

        # правка на B доходит до A
        (await sb.get(CashBalances, 1)).cash_amount = Decimal("2500")
        await sb.commit()
        assert (await hub.обмен(sb, c, day))["pushed"] == 1
        await sa.refresh(await sa.get(CashBalances, 1))
        assert (await hub.обмен(sa, c, day))["pulled"] == 1
        assert (await sa.get(CashBalances, 1)).cash_amount == Decimal("2500.00")


async def test_без_ключа_сервер_закрыт(tmp_path, monkeypatch):
    app = _server(tmp_path, monkeypatch)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://hub") as c:
        assert (await c.get("/v1/changes")).status_code == 401
