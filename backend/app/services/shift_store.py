"""Хранение смены: снимки, время прихода-ухода, отметки об отправке.

Расчёты живут в app/services/shift.py и ничего не знают о базе. Здесь —
только состояние: что уже открыто, что закрыто, что ушло в Telegram.

Главное правило раздела (§31, §32 ТЗ): на дату существует ровно одна смена.
Повторное нажатие кнопки показывает уже существующую, а не заводит вторую.
"""

import re
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.models import Client, Shift, ShiftEmployee
from app.services import cash_balances
from app.services import shift as расчёт
from app.services.telegram import отправить_сообщение

УСЛУГИ = "services"
ТОВАРЫ = "products"

ОТКРЫТИЕ = "opening"
ЗАКРЫТИЕ = "closing"

ЧАСЫ = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def проверить_время(значение: str) -> str:
    """HH:MM в пределах 00:00–23:59 (§29 ТЗ). Иначе — ошибка, а не тихая запись."""
    значение = (значение or "").strip()
    if not ЧАСЫ.match(значение):
        raise ValueError(f"Время «{значение}» не в формате ЧЧ:ММ")
    return значение


async def _найти(session: AsyncSession, день: date) -> Shift | None:
    строка = await session.execute(
        select(Shift).where(Shift.shift_date == день).options(selectinload(Shift.employees))
    )
    return строка.scalars().first()


async def _мастера_смены(session: AsyncSession, смена: Shift, мастера: list[dict]) -> None:
    """Завести строки мастеров смены, не трогая уже введённое время.

    Список запрашивается отдельно, а не берётся из смена.employees: у только
    что созданной смены связь не загружена, и обращение к ней в асинхронной
    сессии уходит в ленивый запрос, которого здесь быть не может.
    """
    строки = await session.execute(
        select(ShiftEmployee.staff_id).where(ShiftEmployee.shift_id == смена.id)
    )
    уже = set(строки.scalars().all())
    for м in мастера:
        ident = int(м["staff_id"])
        if ident in уже:
            continue
        session.add(
            ShiftEmployee(
                shift_id=смена.id,
                staff_id=ident,
                staff_name_snapshot=str(м["name"]),
                arrival_time=None,
                departure_time=None,
            )
        )


def времена(смена: Shift | None, поле: str) -> dict[int, str]:
    if смена is None:
        return {}
    return {
        м.staff_id: getattr(м, поле)
        for м in смена.employees
        if getattr(м, поле)
    }


def состояние(смена: Shift | None) -> dict:
    """Что показывать на экране до нажатия кнопок."""
    if смена is None:
        return {
            "exists": False,
            "opened_at": None,
            "closed_at": None,
            "opening_sent_at": None,
            "closing_sent_at": None,
            "opening_snapshot": None,
            "closing_snapshot": None,
            "employees": [],
        }
    return {
        "exists": True,
        "opened_at": смена.opened_at.isoformat() if смена.opened_at else None,
        "closed_at": смена.closed_at.isoformat() if смена.closed_at else None,
        "opening_sent_at": (
            смена.opening_telegram_sent_at.isoformat()
            if смена.opening_telegram_sent_at
            else None
        ),
        "closing_sent_at": (
            смена.closing_telegram_sent_at.isoformat()
            if смена.closing_telegram_sent_at
            else None
        ),
        "opening_snapshot": смена.opening_snapshot,
        "closing_snapshot": смена.closing_snapshot,
        "employees": [
            {
                "staff_id": м.staff_id,
                "name": м.staff_name_snapshot,
                "arrival_time": м.arrival_time,
                "departure_time": м.departure_time,
            }
            for м in sorted(смена.employees, key=lambda e: e.id)
        ],
    }


async def текущая(session: AsyncSession, день: date | None = None) -> dict:
    день = день or расчёт.moscow_today()
    смена = await _найти(session, день)
    итог = состояние(смена)
    итог["shift_date"] = день.isoformat()
    return итог


async def открыть(session: AsyncSession, день: date | None = None) -> dict:
    """Снимок на утро. Уже открытую смену не пересчитываем (§28 ТЗ).

    Утренний отчёт — это состояние на момент открытия. Отменённая после
    открытия запись утреннюю цифру не меняет: вечером будет свой расчёт.
    """
    день = день or расчёт.moscow_today()
    смена = await _найти(session, день)
    if смена is not None and смена.opening_snapshot:
        return await текущая(session, день)

    снимок = await расчёт.собрать_открытие(день)
    if смена is None:
        смена = Shift(shift_date=день)
        session.add(смена)
        await session.flush()
    смена.opening_snapshot = снимок
    смена.opened_at = datetime.now(UTC)
    await _мастера_смены(session, смена, снимок["masters"])
    await session.commit()
    return await текущая(session, день)


async def закрыть(session: AsyncSession, день: date | None = None) -> dict:
    """Факт за день. Пока закрытие не отправлено — пересчитывается заново (§32 ТЗ)."""
    день = день or расчёт.moscow_today()
    смена = await _найти(session, день)
    if смена is not None and смена.closing_telegram_sent_at is not None:
        return await текущая(session, день)

    снимок = await расчёт.собрать_закрытие(день)
    остатки = await cash_balances.получить(session)
    добавка = cash_balances.в_блок_денег(остатки, день)
    предупреждение_остатков = добавка.pop("warning", None)
    снимок["money"].update(добавка)
    if предупреждение_остатков:
        снимок["warnings"].append(предупреждение_остатков)
    if остатки is None:
        снимок["warnings"].append(
            "Остатки денег ещё не внесены — касса, счёт и долг по другому счёту "
            "недоступны, пока владелец не укажет их хотя бы раз."
        )

    if смена is None:
        смена = Shift(shift_date=день)
        session.add(смена)
        await session.flush()
    смена.closing_snapshot = снимок
    смена.closed_at = datetime.now(UTC)
    await _мастера_смены(session, смена, снимок["masters"])
    await session.commit()
    return await текущая(session, день)


async def записать_времена(
    session: AsyncSession, вид: str, значения: dict[int, str], день: date | None = None
) -> dict:
    """Приход или уход мастеров. Ввод только ручной (§29 ТЗ)."""
    день = день or расчёт.moscow_today()
    поле = "arrival_time" if вид == ОТКРЫТИЕ else "departure_time"
    смена = await _найти(session, день)
    if смена is None:
        raise ValueError("Смена на этот день не открыта")

    по_мастерам = {м.staff_id: м for м in смена.employees}
    for ident, время in значения.items():
        мастер = по_мастерам.get(int(ident))
        if мастер is None:
            raise ValueError(f"Мастер {ident} в этой смене не числится")
        setattr(мастер, поле, проверить_время(время) if время else None)
    await session.commit()
    return await текущая(session, день)


def текст(вид: str, смена: Shift) -> str:
    if вид == ОТКРЫТИЕ:
        if not смена.opening_snapshot:
            raise ValueError("Смена ещё не открыта — нечего отправлять")
        return расчёт.текст_открытия(смена.opening_snapshot, времена(смена, "arrival_time"))
    if not смена.closing_snapshot:
        raise ValueError("Смена ещё не закрыта — нечего отправлять")
    return расчёт.текст_закрытия(смена.closing_snapshot, времена(смена, "departure_time"))


async def предпросмотр(session: AsyncSession, вид: str, день: date | None = None) -> dict:
    день = день or расчёт.moscow_today()
    смена = await _найти(session, день)
    if смена is None:
        raise ValueError("Смена на этот день не открыта")
    return {"text": текст(вид, смена)}


async def деньги_детали(session: AsyncSession, вид: str, день: date | None = None) -> list[dict]:
    """Из чего сложилась плитка «Услуги» или «Товары» в блоке «Деньги».

    Клиент — не бизнес-правило, а справочная подпись, поэтому имя ищем в
    локальной базе по client_id (тот же путь, что и всюду в проекте: имени из
    самой записи YCLIENTS не доверяем, только стабильному id — §26 ТЗ смены).
    Не нашли клиента в базе — оставляем пусто, а не гадаем.
    """
    if вид == УСЛУГИ:
        строки = await расчёт.собрать_детали_услуг(день)
        client_ids = {с["client_id"] for с in строки if с["client_id"] is not None}
        имена: dict[int, str] = {}
        if client_ids:
            найденные = await session.execute(
                select(Client.yclients_id, Client.name).where(Client.yclients_id.in_(client_ids))
            )
            имена = dict(найденные.all())
        return [
            {
                "time": с["time"],
                "client": имена.get(с["client_id"]) if с["client_id"] else None,
                "master": с["master"],
                "title": с["title"],
                "amount": с["amount"],
            }
            for с in строки
        ]
    if вид == ТОВАРЫ:
        return await расчёт.собрать_детали_товаров(день)
    raise ValueError("Раздел должен быть services или products")


async def отправить(session: AsyncSession, вид: str, день: date | None = None) -> dict:
    """Отправка в Telegram — только по отдельному действию человека (§31 ТЗ).

    Повторная отправка не запрещена: бывает, что сообщение ушло не туда или
    время внесли уже после. Но она всегда сознательная — кнопка отдельная, и
    на экране видно, что и когда уже ушло.
    """
    день = день or расчёт.moscow_today()
    смена = await _найти(session, день)
    if смена is None:
        raise ValueError("Смена на этот день не открыта")

    message_id = await отправить_сообщение(текст(вид, смена))
    сейчас = datetime.now(UTC)
    if вид == ОТКРЫТИЕ:
        смена.opening_telegram_sent_at = сейчас
        смена.opening_telegram_message_id = message_id
    else:
        смена.closing_telegram_sent_at = сейчас
        смена.closing_telegram_message_id = message_id
    await session.commit()
    return await текущая(session, день)
