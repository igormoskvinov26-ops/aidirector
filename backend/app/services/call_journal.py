"""Журнал обзвона в Excel — без личных данных клиентов.

Результаты звонков живут в базе Пульта (в Docker), и только там лежат имена,
телефоны. Excel — обычный файл рядом с проектом: его видно,
можно сохранить на флешку и загрузить в новую установку. Поэтому в нём
клиент записан только номером в YCLIENTS — ни имени, ни телефона (решение
владельца 30.10.2026: файл — самое слабое место). Комментарий администратора
остаётся (решение владельца там же).

Строки только дописываются, файл никогда не перестраивается из базы сам.
Старые файлы с именами и телефонами переписываются в новый вид при запуске
(``очистить_старые``): номер YCLIENTS находится по телефону в базе.
"""

import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from loguru import logger
from openpyxl import Workbook, load_workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.models import Client, ContactAttempt, ContactTask

JOURNAL_NAME = "обзвон.xlsx"

# Время в журнале московское, а не то, в котором живёт контейнер: файл читает
# администратор салона и сверяет строки со своей сменой.
MOSCOW = ZoneInfo(settings.timezone)

COLUMNS = (
    "Дата",
    "Время",
    "ID клиента YCLIENTS",
    "Сегмент",
    "Результат",
    "Канал",
    "Комментарий",
    "Кто звонил",
)
# Прежний вид файла (до 9.24.2) — с именем, телефоном и комментарием.
OLD_COLUMNS = (
    "Дата", "Время", "Клиент", "Телефон", "Сегмент", "Результат", "Канал", "Комментарий", "Кто звонил",
)

# Как называются исходы по-русски. Коды остаются в базе, в файл идут слова:
# его открывает администратор, а не программа.
OUTCOMES = {
    "booked": "записался",
    "no_booking": "отказался",
    "no_answer": "не ответил",
    "callback": "перезвонить",
    "do_not_call": "не звонить",
}


def journal_path() -> Path:
    return settings.output_dir / JOURNAL_NAME


def moscow_now() -> datetime:
    return datetime.now(MOSCOW)


def _to_moscow(value: datetime | None) -> datetime:
    """Привести отметку времени к московской. База хранит UTC, иногда наивный."""
    if value is None:
        return moscow_now()
    if value.tzinfo is None:
        return value.replace(tzinfo=ZoneInfo("UTC")).astimezone(MOSCOW)
    return value.astimezone(MOSCOW)


def _open_or_create() -> Workbook:
    path = journal_path()
    if path.exists():
        try:
            return load_workbook(path)
        except Exception as exc:
            # Файл побился или его держит открытым Excel. Терять запись из-за
            # этого нельзя — уводим повреждённый в сторону и начинаем новый.
            broken = path.with_name(f"обзвон-повреждён-{moscow_now():%Y%m%d-%H%M%S}.xlsx")
            logger.warning(f"журнал обзвона не читается ({exc}), сохранён как {broken.name}")
            path.rename(broken)

    book = Workbook()
    sheet = book.active
    sheet.title = "Обзвон"
    sheet.append(list(COLUMNS))
    for index, width in enumerate((12, 8, 20, 18, 14, 10, 40, 16), start=1):
        sheet.column_dimensions[sheet.cell(row=1, column=index).column_letter].width = width
    return book


def _row(
    *,
    when: datetime,
    yclients_id: int | str | None,
    segment: str,
    outcome: str,
    channel: str,
    comment: str | None,
    actor: str | None,
) -> list[str]:
    return [
        when.strftime("%d.%m.%Y"),
        when.strftime("%H:%M"),
        str(yclients_id) if yclients_id else "",
        segment,
        OUTCOMES.get(outcome, outcome),
        "телефон" if channel == "phone" else channel,
        comment or "",
        actor or "",
    ]


def _write_rows(rows: list[list[str]]) -> None:
    """Дописать строки одним открытием файла.

    Ошибка записи не должна ронять звонок: результат уже лежит в базе, а
    администратор должен доработать смену.
    """
    if not rows:
        return
    try:
        settings.output_dir.mkdir(parents=True, exist_ok=True)
        book = _open_or_create()
        sheet = book.active
        for row in rows:
            sheet.append(row)
        book.save(journal_path())
    except Exception as exc:
        logger.error(f"не удалось записать в журнал обзвона: {exc}")


def append_row(**fields: object) -> None:
    """Дописать одну строку."""
    _write_rows([_row(**fields)])  # type: ignore[arg-type]


async def append_attempt(
    session: AsyncSession,
    task_id: int,
    attempt: ContactAttempt,
    when: datetime | None = None,
) -> None:
    """Собрать данные о звонке и дописать строку.

    ``when`` передаётся вызывающим: ``created_at`` заполняет сервер базы, и
    сразу после вставки в объекте его ещё нет.
    """
    task = await session.get(ContactTask, task_id)
    if task is None:
        return
    client = await session.get(Client, task.client_id)
    append_row(
        when=_to_moscow(when),
        yclients_id=client.yclients_id if client else None,
        segment=task.group_code,
        outcome=attempt.outcome,
        channel=attempt.channel,
        comment=attempt.comment,
        actor=attempt.actor_id,
    )


async def rebuild_from_database(session: AsyncSession) -> int:
    """Собрать журнал заново из базы. Только по явной просьбе.

    Нужно, если журнал потерялся, а база цела — обратный случай к обычному.
    Существующий файл при этом отодвигается в сторону, а не затирается.
    """
    path = journal_path()
    if path.exists():
        backup = path.with_name(f"обзвон-до-пересборки-{moscow_now():%Y%m%d-%H%M%S}.xlsx")
        path.rename(backup)
        logger.info(f"прежний журнал сохранён как {backup.name}")

    rows = await session.execute(
        select(ContactAttempt, ContactTask, Client)
        .join(ContactTask, ContactAttempt.task_id == ContactTask.id)
        .join(Client, ContactTask.client_id == Client.id)
        .order_by(ContactAttempt.created_at)
    )
    batch = [
        _row(
            when=_to_moscow(attempt.created_at),
            yclients_id=client.yclients_id,
            segment=task.group_code,
            outcome=attempt.outcome,
            channel=attempt.channel,
            comment=attempt.comment,
            actor=attempt.actor_id,
        )
        for attempt, task, client in rows
    ]
    _write_rows(batch)
    return len(batch)


def _цифры(s: object) -> str:
    return re.sub(r"\D", "", str(s or ""))


async def номера_по_телефону(session: AsyncSession) -> dict[str, int]:
    """Последние 10 цифр телефона → номер клиента в YCLIENTS (для старых файлов)."""
    rows = (await session.execute(select(Client.phone, Client.yclients_id))).all()
    return {_цифры(phone)[-10:]: yid for phone, yid in rows if _цифры(phone)}


def старый_вид(path: Path) -> bool:
    """Файл прежнего вида — с колонками «Клиент» и «Телефон»."""
    try:
        book = load_workbook(path, read_only=True)
        header = list(next(book.active.iter_rows(max_row=1, values_only=True), None) or [])
        book.close()
    except Exception:
        return False
    return header[: len(OLD_COLUMNS)] == list(OLD_COLUMNS)


def read_journal(path: Path, номера: dict[str, int] | None = None) -> list[dict]:
    """Прочитать журнал — свой или из прошлой установки — в новом виде.

    Файл старого вида (с именем и телефоном) тоже принимается: номер YCLIENTS
    ищется по телефону в ``номера``, а имя и телефон отбрасываются.
    """
    book = load_workbook(path, read_only=True, data_only=True)
    sheet = book.active
    rows = sheet.iter_rows(values_only=True)

    header = list(next(rows, None) or [])
    if header[: len(COLUMNS)] == list(COLUMNS):
        старый = False
    elif header[: len(OLD_COLUMNS)] == list(OLD_COLUMNS):
        старый = True
    else:
        raise ValueError(
            "Это не журнал обзвона: в первой строке должны стоять заголовки "
            + ", ".join(COLUMNS)
        )

    result = []
    for row in rows:
        if not row or not any(row):
            continue
        if старый:
            r = dict(zip(OLD_COLUMNS, row, strict=False))
            record = {name: r.get(name) for name in COLUMNS if name in r}
            найден = (номера or {}).get(_цифры(r.get("Телефон"))[-10:])
            record["ID клиента YCLIENTS"] = str(найден) if найден else ""
        else:
            record = dict(zip(COLUMNS, row, strict=False))
        if not record.get("Дата"):
            continue
        result.append(record)
    return result


def _key(record: dict) -> tuple:
    """Чем строка отличается от другой. Дважды один и тот же звонок не нужен."""
    return tuple(str(record.get(name) or "").strip() for name in
                 ("Дата", "Время", "ID клиента YCLIENTS", "Результат"))


def merge_journal(source: Path, номера: dict[str, int] | None = None) -> dict:
    """Влить журнал прошлой установки в нынешний.

    Записи в базу не идут: задач из старой установки здесь нет, и придумывать
    их — значит засорять очередь обзвона несуществующими клиентами. История
    звонков нужна для анализа, и живёт она в файле.
    """
    incoming = read_journal(source, номера)
    existing = read_journal(journal_path(), номера) if journal_path().exists() else []
    known = {_key(record) for record in existing}

    fresh = []
    for record in incoming:
        key = _key(record)
        if key in known:
            continue
        known.add(key)
        fresh.append([record.get(name) or "" for name in COLUMNS])

    _write_rows(fresh)
    return {"прочитано": len(incoming), "добавлено": len(fresh),
            "пропущено_дублей": len(incoming) - len(fresh)}


def выгрузка(path: Path, номера: dict[str, int] | None = None) -> bytes:
    """Журнал для скачивания — всегда собирается заново в новом виде.

    Файл с диска как есть наружу не отдаётся: если там остался журнал
    прежнего вида с именами и телефонами (очистка не сработала, старая
    копия), в выгрузку всё равно попадут только номер YCLIENTS и цифры.
    """
    import io

    book = Workbook()
    sheet = book.active
    sheet.title = "Обзвон"
    sheet.append(list(COLUMNS))
    for record in read_journal(path, номера):
        sheet.append([record.get(name) or "" for name in COLUMNS])
    buf = io.BytesIO()
    book.save(buf)
    return buf.getvalue()


async def очистить_старые(session: AsyncSession) -> int:
    """Переписать файлы журнала старого вида без имён и телефонов.

    Касается и основного файла, и отодвинутых копий («обзвон-повреждён-…»,
    «обзвон-до-пересборки-…»). Вызывается при запуске Пульта; файл нового вида
    не трогается. Возвращает число переписанных файлов.
    """
    папка = settings.output_dir
    if not папка.exists():
        return 0
    номера = None
    переписано = 0
    for path in sorted(папка.glob("обзвон*.xlsx")):
        if not старый_вид(path):
            continue
        if номера is None:
            номера = await номера_по_телефону(session)
        строки = read_journal(path, номера)
        новый = Workbook()
        sheet = новый.active
        sheet.title = "Обзвон"
        sheet.append(list(COLUMNS))
        for record in строки:
            sheet.append([record.get(name) or "" for name in COLUMNS])
        временный = path.with_suffix(".tmp")
        новый.save(временный)
        временный.replace(path)  # старый файл с личными данными заменён целиком
        переписано += 1
        logger.info(f"журнал {path.name}: убраны имена и телефоны ({len(строки)} строк)")
    return переписано
