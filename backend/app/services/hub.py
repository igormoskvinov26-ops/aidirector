"""Общий сервер расчётных показателей: синхронизация между установками.

Решение владельца 04.10.2026. На сервер уходит только то, что посчитали мы
сами: смены, остатки кассы, строки отчёта банка, точка отсчёта пульса,
настройки отчёта. Клиентов, телефонов и записей среди этого нет.

Схема: документ = ключ + JSON. Клиент ведёт в app_settings таблицу
``hub_state`` {ключ: хеш последней согласованной копии и номер версии на
сервере}. Если локальный хеш изменился, документ отправляется с номером
версии, на которой основан; сервер при расхождении отвечает 409, и тогда
побеждает серверная копия (одновременная правка одного документа с двух
компьютеров за полминуты, потеря локальной правки здесь осознанна).
Поля, которые меняет сама база (updated_at), в документы не входят: иначе
после применения чужой правки хеш менялся бы и документы вечно гоняло бы
туда-обратно.
"""

import asyncio
import re
import hashlib
import json
import socket
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
from loguru import logger
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    AcquiringRow,
    AppSetting,
    CashBalances,
    ReportSetting,
    Shift,
    ShiftEmployee,
)
from app.services import configuration

STATE_KEY = "hub_state"
PULSE_KEY = "pulse_start_date"
SHIFT_WINDOW_DAYS = 45
ACQ_WINDOW_DAYS = 120
INTERVAL_SECONDS = 45
_lock = asyncio.Lock()
status: dict[str, Any] = {"ok": None, "at": None, "error": None, "pushed": 0, "pulled": 0}


def настроен() -> bool:
    return bool(configuration.значение("HUB_URL") and configuration.значение("HUB_TOKEN"))


def _клиент() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=configuration.значение("HUB_URL").rstrip("/"),
        headers={"Authorization": f"Bearer {configuration.значение('HUB_TOKEN')}",
                 "X-Writer": socket.gethostname()[:60]},
        timeout=20.0,
    )


async def проверить() -> str:
    if not настроен():
        raise ValueError("Впишите адрес сервера и ключ доступа")
    try:
        async with _клиент() as c:
            r = await c.get("/v1/health")
    except httpx.HTTPError as e:
        raise RuntimeError("Сервер не отвечает: проверьте адрес и интернет") from e
    if r.status_code in (401, 403):
        raise ValueError("Сервер не принял ключ доступа")
    if r.status_code != 200:
        raise RuntimeError(f"Сервер ответил {r.status_code}")
    return "Сервер отвечает, ключ принят"


# ── Локальные документы ───────────────────────────────────────────────────


def _utc(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return dt.isoformat()


def _из_utc(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


def _хеш(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


async def _смена_в_документ(session: AsyncSession, смена: Shift) -> dict:
    people = (await session.execute(
        select(ShiftEmployee).where(ShiftEmployee.shift_id == смена.id).order_by(ShiftEmployee.staff_id)
    )).scalars().all()
    return {
        "opened_at": _utc(смена.opened_at), "closed_at": _utc(смена.closed_at),
        "opening_snapshot": смена.opening_snapshot, "closing_snapshot": смена.closing_snapshot,
        "opening_telegram_sent_at": _utc(смена.opening_telegram_sent_at),
        "opening_telegram_message_id": смена.opening_telegram_message_id,
        "closing_telegram_sent_at": _utc(смена.closing_telegram_sent_at),
        "closing_telegram_message_id": смена.closing_telegram_message_id,
        "employees": [{"staff_id": p.staff_id, "name": p.staff_name_snapshot,
                       "arrival": p.arrival_time, "departure": p.departure_time} for p in people],
    }


async def локальные(session: AsyncSession, today: date | None = None) -> dict[str, Any]:
    today = today or datetime.now(UTC).date()
    docs: dict[str, Any] = {}
    b = (await session.execute(select(CashBalances).where(CashBalances.id == 1))).scalars().first()
    if b is not None:
        docs["balances"] = {
            "cash_amount": str(b.cash_amount), "cash_as_of": b.cash_as_of.isoformat(),
            "settlement_amount": str(b.settlement_amount), "settlement_as_of": b.settlement_as_of.isoformat(),
            "other_account_debt": str(b.other_account_debt), "other_debt_note": b.other_debt_note,
        }
    p = await session.get(AppSetting, PULSE_KEY)
    if p is not None and p.value:
        docs["pulse_start"] = p.value
    rs = (await session.execute(select(ReportSetting))).scalars().all()
    if rs:
        docs["report_settings"] = {r.key: r.value for r in rs}
    since = today - timedelta(days=SHIFT_WINDOW_DAYS)
    for смена in (await session.execute(select(Shift).where(Shift.shift_date >= since))).scalars():
        docs[f"shift:{смена.shift_date.isoformat()}"] = await _смена_в_документ(session, смена)
    by_day: dict[str, list] = {}
    rows = (await session.execute(
        select(AcquiringRow).where(AcquiringRow.op_date >= today - timedelta(days=ACQ_WINDOW_DAYS))
        .order_by(AcquiringRow.op_date, AcquiringRow.id)
    )).scalars()
    for r in rows:
        by_day.setdefault(r.op_date.isoformat(), []).append(
            {"amount": str(r.amount), "fee": str(r.fee), "net": str(r.net), "file": r.source_file})
    for day, items in by_day.items():
        docs[f"acq:{day}"] = items
    return docs


async def _применить(session: AsyncSession, key: str, value: Any) -> None:
    if key == "balances":
        b = (await session.execute(select(CashBalances).where(CashBalances.id == 1))).scalars().first()
        if b is None:
            b = CashBalances(id=1)
            session.add(b)
        b.cash_amount, b.cash_as_of = Decimal(value["cash_amount"]), date.fromisoformat(value["cash_as_of"])
        b.settlement_amount = Decimal(value["settlement_amount"])
        b.settlement_as_of = date.fromisoformat(value["settlement_as_of"])
        b.other_account_debt, b.other_debt_note = Decimal(value["other_account_debt"]), value["other_debt_note"]
    elif key == "pulse_start":
        row = await session.get(AppSetting, PULSE_KEY)
        if row is None:
            session.add(AppSetting(key=PULSE_KEY, value=value))
        else:
            row.value = value
    elif key == "report_settings":
        for k, v in value.items():
            row = await session.get(ReportSetting, k)
            if row is None:
                session.add(ReportSetting(key=k, value=v))
            else:
                row.value = v
        await session.flush()
        from app.services import salon

        await salon.загрузить(session)
    elif key.startswith("shift:"):
        day = date.fromisoformat(key[6:])
        смена = (await session.execute(select(Shift).where(Shift.shift_date == day))).scalars().first()
        if смена is None:
            смена = Shift(shift_date=day)
            session.add(смена)
            await session.flush()
        смена.opened_at, смена.closed_at = _из_utc(value["opened_at"]), _из_utc(value["closed_at"])
        смена.opening_snapshot, смена.closing_snapshot = value["opening_snapshot"], value["closing_snapshot"]
        смена.opening_telegram_sent_at = _из_utc(value["opening_telegram_sent_at"])
        смена.opening_telegram_message_id = value["opening_telegram_message_id"]
        смена.closing_telegram_sent_at = _из_utc(value["closing_telegram_sent_at"])
        смена.closing_telegram_message_id = value["closing_telegram_message_id"]
        await session.execute(delete(ShiftEmployee).where(ShiftEmployee.shift_id == смена.id))
        for e in value["employees"]:
            session.add(ShiftEmployee(shift_id=смена.id, staff_id=e["staff_id"], staff_name_snapshot=e["name"],
                                      arrival_time=e["arrival"], departure_time=e["departure"]))
    elif key.startswith("acq:"):
        day = date.fromisoformat(key[4:])
        await session.execute(delete(AcquiringRow).where(AcquiringRow.op_date == day))
        for r in value:
            session.add(AcquiringRow(op_date=day, amount=Decimal(r["amount"]), fee=Decimal(r["fee"]),
                                     net=Decimal(r["net"]), source_file=r["file"]))
    else:
        return
    await session.commit()


# ── Обмен ─────────────────────────────────────────────────────────────────


async def _состояние(session: AsyncSession) -> dict:
    row = await session.get(AppSetting, STATE_KEY)
    return json.loads(row.value) if row and row.value else {"cursor": 0, "docs": {}}


async def _сохранить_состояние(session: AsyncSession, state: dict) -> None:
    row = await session.get(AppSetting, STATE_KEY)
    text = json.dumps(state)
    if row is None:
        session.add(AppSetting(key=STATE_KEY, value=text))
    else:
        row.value = text
    await session.commit()


_ЧУЖОЙ = re.compile(r"^c\d+\.")


def _префикс() -> str:
    """Главный филиал пишет как раньше, остальные — с номером компании в ключе."""
    from app.services import branches

    if branches.главный():
        return ""
    return f"c{configuration.число('YCLIENTS_COMPANY_ID')}."


def _свой_ключ(key: str, pre: str) -> str | None:
    if pre:
        return key[len(pre):] if key.startswith(pre) else None
    return None if _ЧУЖОЙ.match(key) else key


async def обмен(session: AsyncSession, client: httpx.AsyncClient, today: date | None = None) -> dict:
    """Один цикл: отправить изменённое, затем забрать чужое."""
    state = await _состояние(session)
    known: dict = state["docs"]
    pushed = pulled = 0
    pre = _префикс()
    for key, value in (await локальные(session, today)).items():
        h = _хеш(value)
        st = known.get(key)
        if st and st["h"] == h:
            continue
        r = await client.put(f"/v1/doc/{pre}{key}", json={"value": value, "base_seq": st["seq"] if st else 0})
        if r.status_code == 409:
            continue  # серверная копия новее: заберём её ниже
        r.raise_for_status()
        known[key] = {"h": h, "seq": r.json()["seq"]}
        pushed += 1
    r = await client.get("/v1/changes", params={"since": state["cursor"]})
    r.raise_for_status()
    body = r.json()
    for d in body["docs"]:
        key = _свой_ключ(d["key"], pre)
        if key is None:
            continue  # документ другого филиала
        st = known.get(key)
        if st and st["seq"] >= d["seq"]:
            continue
        await _применить(session, key, d["value"])
        now_local = (await локальные(session, today)).get(key, d["value"])
        known[key] = {"h": _хеш(now_local), "seq": d["seq"]}
        pulled += 1
    state["cursor"] = body["seq"]
    await _сохранить_состояние(session, state)
    return {"pushed": pushed, "pulled": pulled}


async def один_цикл() -> None:
    from app.database import async_session

    if not настроен() or _lock.locked():
        return
    if _префикс() == "c0.":  # у нового филиала ещё нет номера компании
        return
    async with _lock:
        try:
            async with _клиент() as c, async_session() as session:
                итог = await обмен(session, c)
            status.update(ok=True, error=None, at=datetime.now(UTC).isoformat(), **итог)
            if итог["pushed"] or итог["pulled"]:
                logger.info(f"общий сервер: отправлено {итог['pushed']}, получено {итог['pulled']}")
        except Exception as e:  # noqa: BLE001
            status.update(ok=False, error=f"{type(e).__name__}: {e}"[:200], at=datetime.now(UTC).isoformat())
            logger.warning(f"общий сервер недоступен, повторю: {status['error']}")


async def run_hub_loop() -> None:
    await asyncio.sleep(20)
    while True:
        await один_цикл()
        await asyncio.sleep(INTERVAL_SECONDS)
