"""Журнал обзвона в Excel.

Результаты звонков живут в базе, но база — в контейнере, и человеку её не
открыть. Журнал — обычный файл рядом с проектом: его видно, можно сохранить
на флешку, отправить, посмотреть в Excel и загрузить в новую установку.

Строки только дописываются, файл никогда не перестраивается из базы. Это
намеренно: если база потеряется, перестроение стёрло бы и журнал, то есть
ровно то, ради чего он заведён.
"""

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
MOSCOW = ZoneInfo("Europe/Moscow")

COLUMNS = (
    "Дата",
    "Время",
    "Клиент",
    "Телефон",
    "Сегмент",
    "Результат",
    "Канал",
    "Комментарий",
    "Кто звонил",
)

# Как называются исходы по-русски. Коды остаются в базе, в файл идут слова:
# его открывает администратор, а не программа.
OUTCOMES = {
    "booked": "записался",
    "no_booking": "отказался",
    "no_answer": "не ответил",
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
    for index, width in enumerate((12, 8, 28, 18, 18, 14, 10, 40, 16), start=1):
        sheet.column_dimensions[sheet.cell(row=1, column=index).column_letter].width = width
    return book


def _row(
    *,
    when: datetime,
    client_name: str,
    phone: str,
    segment: str,
    outcome: str,
    channel: str,
    comment: str | None,
    actor: str | None,
) -> list[str]:
    return [
        when.strftime("%d.%m.%Y"),
        when.strftime("%H:%M"),
        client_name,
        phone,
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
        client_name=(client.name if client else "") or "Без имени",
        phone=(client.phone if client else "") or "",
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
            client_name=client.name or "Без имени",
            phone=client.phone or "",
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


def read_journal(path: Path) -> list[dict]:
    """Прочитать журнал — свой или из прошлой установки.

    Возвращает строки как они есть. Сопоставление с клиентами и запись в базу
    делает вызывающий: здесь только чтение файла.
    """
    book = load_workbook(path, read_only=True, data_only=True)
    sheet = book.active
    rows = sheet.iter_rows(values_only=True)

    header = next(rows, None)
    if not header or list(header)[: len(COLUMNS)] != list(COLUMNS):
        raise ValueError(
            "Это не журнал обзвона: в первой строке должны стоять заголовки "
            + ", ".join(COLUMNS)
        )

    result = []
    for row in rows:
        if not row or not any(row):
            continue
        record = dict(zip(COLUMNS, row, strict=False))
        if not record.get("Телефон") and not record.get("Клиент"):
            continue
        result.append(record)
    return result


def _key(record: dict) -> tuple:
    """Чем строка отличается от другой. Дважды один и тот же звонок не нужен."""
    return tuple(str(record.get(name) or "").strip() for name in
                 ("Дата", "Время", "Телефон", "Результат"))


def merge_journal(source: Path) -> dict:
    """Влить журнал прошлой установки в нынешний.

    Записи в базу не идут: задач из старой установки здесь нет, и придумывать
    их — значит засорять очередь обзвона несуществующими клиентами. История
    звонков нужна для анализа, и живёт она в файле.
    """
    incoming = read_journal(source)
    existing = read_journal(journal_path()) if journal_path().exists() else []
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
