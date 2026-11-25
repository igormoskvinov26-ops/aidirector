"""Client base routes — segmentation, dashboard, admin contact queue."""

import tempfile
from datetime import date
from pathlib import Path

from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.main_roles import ROLE_OWNER
from app.services import call_journal, client_base, finance
from app.services.client_base import moscow_today

router = APIRouter(prefix="/api/client-base", tags=["client-base"])


@router.get("/dashboard")
async def dashboard(
    period: str = Query("month", description="day|week|month|quarter|year"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await client_base.build_dashboard(db, period)


@router.get("/counters")
async def counters(db: AsyncSession = Depends(get_db)) -> dict:
    """Повторные и потерянные клиенты — на весь салон, без привязки к мастеру.

    Показывается и здесь, и на «Записях за месяц» — решение владельца
    18.09.2026. Подробности расчёта: app/services/finance.py:get_repeat_and_lost_clients.
    """
    return await finance.get_repeat_and_lost_clients(db)


@router.get("/snapshots")
async def snapshots(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    return await client_base.get_snapshots(db, days)


@router.get("/timeseries")
async def timeseries(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    return await client_base.backfill_timeseries(db, days)


@router.get("/metric-history")
async def metric_history(
    days: int = Query(90, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """История для графика по клику на плитку — «Повторные»/«Потерянные» и
    показатели мастеров (потерянные/новые/уникальные клиенты/возвращаемость).

    Один запрос на обе страницы: подробности формата ключей и метода —
    app/services/client_base.py:backfill_metric_history.
    """
    return await client_base.backfill_metric_history(db, days)


@router.get("/pulse")
async def pulse(db: AsyncSession = Depends(get_db)) -> dict:
    """Пять сегментов базы плюс зона риска, в разрезе мастеров — для гистограмм.

    Решение владельца 25.09.2026. Подробности разбивки:
    app/services/client_base.py:classify_client, :в_зоне_риска.
    """
    return await client_base.build_base_pulse(db)


@router.get("/flow")
async def flow(db: AsyncSession = Depends(get_db)) -> dict:
    """Баланс базы: новые, потерянные и накопленный пульс по дням."""
    return await client_base.build_base_flow(db)


@router.post("/flow/start")
async def flow_start(request: Request, payload: dict = Body(...), db: AsyncSession = Depends(get_db)) -> dict:
    """Точка отсчёта пульса. Только владелец: от неё зависят все цифры."""
    if getattr(request.state, "role", None) != ROLE_OWNER:
        raise HTTPException(status_code=403, detail="Только для владельца")
    try:
        value = date.fromisoformat(str(payload.get("start")))
    except ValueError:
        raise HTTPException(status_code=422, detail="Дата в формате ГГГГ-ММ-ДД") from None
    if value > moscow_today():
        raise HTTPException(status_code=422, detail="Дата не может быть в будущем")
    await client_base.set_pulse_start(db, value)
    return await client_base.build_base_flow(db)


@router.get("/pulse-clients")
async def pulse_clients(
    segment: str = Query(..., description="new|second|loyal|vip|lost|risk"),
    staff_id: int = Query(..., description="yclients_id мастера, 0 — без своего мастера"),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Поимённо те, кто стоит за одним столбцом гистограммы «Пульса базы»."""
    return await client_base.get_pulse_clients(db, segment, staff_id)


@router.get("/clients")
async def clients_by_segment(
    segment: str = Query(..., description="active|due|risk|late|lost|active_base|new|became_regular|returned"),
    period: str = Query("month"),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    return await client_base.get_clients_by_segment(db, segment, period)


@router.get("/segments")
async def segments(db: AsyncSession = Depends(get_db)) -> dict:
    profiles = await client_base.build_client_profiles(db)
    result = {}
    for cid, p in profiles.items():
        result[cid] = p
    return {"clients": result}


@router.post("/sync")
async def sync(db: AsyncSession = Depends(get_db)) -> dict:
    snapshot = await client_base.write_snapshot(db)
    tasks = await client_base.refresh_tasks(db)
    return {"ok": True, "snapshot": snapshot, "tasks": tasks}


@router.get("/sync/status")
async def sync_status(db: AsyncSession = Depends(get_db)) -> dict:
    snaps = await client_base.get_snapshots(db, days=1)
    last_date = snaps[-1]["date"] if snaps else None
    return {
        "last_snapshot_at": last_date,
        "is_stale": last_date != moscow_today().isoformat(),
    }


@router.get("/tasks")
async def tasks(
    status: str = Query("open"),
    admin: str | None = Query(None, description="Имя админа — подставляется в скрипт"),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    return await client_base.get_tasks(db, status, admin)


@router.patch("/clients/{client_id}/note")
async def save_admin_note(
    client_id: int,
    body: dict = Body(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Заметка администратора на карточке клиента, например «перезвонить завтра».

    Хранится на клиенте, а не на сегодняшней задаче обзвона: задачи
    пересобираются каждый день заново, заметка должна это пережить.
    """
    note = str(body.get("note", ""))
    return await client_base.set_admin_note(db, client_id, note)


@router.post("/tasks/{task_id}/outcome")
async def task_outcome(
    task_id: int,
    body: dict = Body(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    outcome = str(body.get("outcome", ""))
    channel = str(body.get("channel", "phone"))
    comment = body.get("comment")
    actor_id = body.get("actor_id")
    admin_staff_id = body.get("admin_staff_id")
    try:
        admin_staff_id = int(admin_staff_id) if admin_staff_id not in (None, "") else None
    except (TypeError, ValueError):
        admin_staff_id = None
    значение = body.get("next_contact")
    try:
        дата = date.fromisoformat(значение) if значение else None
    except ValueError:
        raise HTTPException(status_code=400, detail="Дата в формате ГГГГ-ММ-ДД")
    # Клиент, которого администратор видит на экране, — см. record_outcome.
    client_id = body.get("client_id")
    try:
        client_id = int(client_id) if client_id not in (None, "") else None
    except (TypeError, ValueError):
        client_id = None
    итог = await client_base.record_outcome(
        db, task_id, outcome, channel, comment, actor_id, admin_staff_id, дата,
        client_id=client_id,
    )
    if not итог.get("ok"):
        raise HTTPException(status_code=400, detail=итог.get("error", "не сохранено"))
    return итог


@router.post("/clients/{client_id}/do-not-call")
async def do_not_call(
    client_id: int, request: Request, body: dict = Body(...), db: AsyncSession = Depends(get_db),
) -> dict:
    """«НЕ ЗВОНИТЬ!»: пометить может администратор, снять — только управляющий
    или Владелец (чтобы пометку нельзя было снять по ошибке у стойки)."""
    from app.main_roles import ROLE_OWNER

    value = bool(body.get("value", True))
    if not value and getattr(request.state, "role", None) != ROLE_OWNER:
        raise HTTPException(status_code=403, detail="Снять пометку может только управляющий")
    return await client_base.set_do_not_call(db, client_id, value, body.get("actor"))


@router.get("/returned")
async def returned(
    month: str | None = Query(None, description="ГГГГ-ММ, по умолчанию текущий"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Кого обзвон вернул из потерянных: статистика месяца, график, список."""
    return await client_base.returned_clients(db, month)


@router.get("/calls")
async def calls(
    period: str = Query("month", description="week|month|quarter"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Вкладка «Обзвоны»: совершённые звонки подгруппами по результату."""
    return await client_base.calls_feed(db, period)


@router.get("/search")
async def search(
    phone: str = Query("", description="Любые цифры номера, от трёх"),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Поиск клиента по цифрам телефона — по всей базе, не только по очереди."""
    return await client_base.search_by_phone(db, phone)


@router.get("/base")
async def base(db: AsyncSession = Depends(get_db)) -> dict:
    """Вся клиентская база: очередь на сегодня — признаки строк, не отдельный список."""
    return {"rows": await client_base.вся_база(db), "yclients_url": client_base.шаблон_yclients()}


@router.get("/clients/{client_id}/card")
async def client_card(client_id: int, admin: str | None = Query(None),
                      db: AsyncSession = Depends(get_db)) -> dict:
    """Карточка обзвона любого клиента базы (скрипт, статусы, кнопки)."""
    карточка = await client_base.карточка_клиента(db, client_id, admin)
    if карточка is None:
        raise HTTPException(status_code=404, detail="клиент не найден")
    return карточка


@router.post("/clients/{client_id}/open")
async def open_client(client_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    """Найденного поиском клиента — в сегодняшнюю очередь, чтобы отметить звонок."""
    итог = await client_base.open_from_search(db, client_id)
    if not итог.get("ok"):
        raise HTTPException(status_code=404, detail=итог.get("error"))
    return итог


@router.get("/call-log")
async def call_log(
    date_from: date | None = Query(None, alias="from", description="ГГГГ-ММ-ДД; пусто — всё время"),
    date_to: date | None = Query(None, alias="to", description="ГГГГ-ММ-ДД включительно"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Журнал обзвона: каждое нажатие кнопки результата, новые сверху."""
    return await client_base.call_log(db, date_from, date_to)


@router.get("/tags")
async def tags(db: AsyncSession = Depends(get_db)) -> list[dict]:
    return await client_base.tags_list(db)


@router.post("/tags")
async def save_tag(
    request: Request, body: dict = Body(...), db: AsyncSession = Depends(get_db)
) -> dict:
    """Завести или поправить тег.

    Заводит и администратор — прямо в строке тегов на карточке обзвона
    (решение владельца 16.10.2026). Удаление осталось за управляющим: это
    снимает тег со всех клиентов разом.
    """
    return await client_base.save_tag(db, body)


@router.delete("/tags/{tag_id}")
async def delete_tag(
    tag_id: int, request: Request, db: AsyncSession = Depends(get_db)
) -> dict:
    if getattr(request.state, "role", None) != ROLE_OWNER:
        raise HTTPException(status_code=403, detail="Теги удаляет управляющий")
    return await client_base.delete_tag(db, tag_id)


@router.post("/clients/{client_id}/tags/{tag_id}")
async def set_client_tag(
    client_id: int, tag_id: int, body: dict = Body(default={}),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Повесить или снять тег с клиента — это делает и администратор."""
    return await client_base.set_client_tag(
        db, client_id, tag_id, bool(body.get("value", True)), body.get("actor")
    )


@router.post("/clients/{client_id}/next-contact")
async def next_contact(
    client_id: int, body: dict = Body(...), db: AsyncSession = Depends(get_db)
) -> dict:
    """Запланировать следующий контакт. Пустая дата снимает план."""
    значение = body.get("date")
    try:
        когда = date.fromisoformat(значение) if значение else None
    except ValueError:
        raise HTTPException(status_code=400, detail="Дата в формате ГГГГ-ММ-ДД")
    return await client_base.set_next_contact(db, client_id, когда, body.get("note"), body.get("actor"))


@router.post("/clients/{client_id}/loyalty")
async def loyalty(
    client_id: int, body: dict = Body(...), db: AsyncSession = Depends(get_db)
) -> dict:
    """Светофор лояльности. Повторное нажатие того же цвета его гасит."""
    итог = await client_base.set_loyalty(db, client_id, body.get("value"), body.get("actor"))
    if not итог.get("ok"):
        raise HTTPException(status_code=400, detail=итог.get("error", "не сохранено"))
    return итог


@router.delete("/scripts/{kind}/{key}/{variant}")
async def delete_script(
    kind: str, key: str, variant: str, request: Request, db: AsyncSession = Depends(get_db)
) -> dict:
    if getattr(request.state, "role", None) != ROLE_OWNER:
        raise HTTPException(status_code=403, detail="Скрипты правит управляющий")
    return await client_base.delete_script(db, kind, key, variant)


@router.get("/scripts")
async def scripts(db: AsyncSession = Depends(get_db)) -> dict:
    return await client_base.scripts_all(db)


@router.post("/scripts")
async def save_script(
    request: Request, body: dict = Body(...), db: AsyncSession = Depends(get_db)
) -> dict:
    if getattr(request.state, "role", None) != ROLE_OWNER:
        raise HTTPException(status_code=403, detail="Скрипты правит управляющий")
    итог = await client_base.save_script(
        db, body.get("kind", ""), body.get("key", ""),
        body.get("phone_text"), body.get("message_text"), body.get("actor"),
        body.get("variant") or "main", body.get("title"), body.get("hint"),
    )
    if not итог.get("ok"):
        raise HTTPException(status_code=400, detail=итог.get("error", "не сохранено"))
    return итог


@router.get("/calls/today")
async def calls_today(
    admin_staff_id: int | None = Query(None), db: AsyncSession = Depends(get_db)
) -> dict:
    return await client_base.calls_today(db, admin_staff_id)


@router.get("/admins")
async def call_admins(db: AsyncSession = Depends(get_db)) -> list[dict]:
    """Кто может звонить: список из настроек отчёта. Нужен для выбора имени."""
    from app.services import monthly_report

    return [{"staff_id": a["staff_id"], "name": a["name"]}
            for a in await monthly_report.current_admins(db)]


# --------------------------------------------------------------------------- #
# Журнал обзвона
#
# Результаты звонков лежат в базе, но база живёт в контейнере. Журнал — обычный
# xlsx рядом с проектом: его можно открыть, посчитать в нём что угодно и
# перенести в новую установку.
# --------------------------------------------------------------------------- #


def _require_owner(request: Request) -> None:
    if getattr(request.state, "role", None) != ROLE_OWNER:
        raise HTTPException(status_code=403, detail="Раздел доступен только владельцу")


@router.get("/journal")
async def journal_download(db: AsyncSession = Depends(get_db)) -> Response:
    """Excel-журнал для скачивания: только номер клиента YCLIENTS, без имени
    и телефона — даже если на диске лежит файл прежнего вида."""
    from urllib.parse import quote

    path = call_journal.journal_path()
    if not path.exists():
        raise HTTPException(status_code=404, detail="Журнал пока пуст: не было ни одного звонка")
    номера = await call_journal.номера_по_телефону(db) if call_journal.старый_вид(path) else None
    return Response(
        call_journal.выгрузка(path, номера),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(call_journal.JOURNAL_NAME)}"},
    )


@router.get("/journal/status")
async def journal_status() -> dict:
    path = call_journal.journal_path()
    if not path.exists():
        return {"exists": False, "rows": 0, "path": str(path)}
    try:
        rows = len(call_journal.read_journal(path))
    except Exception:
        rows = 0
    return {"exists": True, "rows": rows, "path": str(path)}


@router.post("/journal/import")
async def journal_import(request: Request, file: UploadFile = File(...),
                         db: AsyncSession = Depends(get_db)) -> dict:
    """Влить журнал прошлой установки. Строки дописываются, дубли пропускаются."""
    _require_owner(request)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix != ".xlsx":
        raise HTTPException(status_code=400, detail="Нужен файл .xlsx")

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(await file.read())
        temp_path = Path(tmp.name)
    try:
        # Старый журнал с именами и телефонами тоже принимается: номер
        # YCLIENTS находится по телефону, имя и телефон в файл не попадают.
        номера = await call_journal.номера_по_телефону(db) if call_journal.старый_вид(temp_path) else None
        return call_journal.merge_journal(temp_path, номера)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        temp_path.unlink(missing_ok=True)


@router.post("/journal/rebuild")
async def journal_rebuild(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    """Собрать журнал заново из базы — если файл потерялся, а база цела.

    Прежний файл не затирается, а отодвигается в сторону.
    """
    _require_owner(request)
    written = await call_journal.rebuild_from_database(db)
    return {"ok": True, "строк": written}
