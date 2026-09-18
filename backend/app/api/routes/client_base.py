"""Client base routes — segmentation, dashboard, admin contact queue."""

import tempfile
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
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.main_roles import ROLE_OWNER
from app.services import call_journal, client_base
from app.services.client_base import moscow_today

router = APIRouter(prefix="/api/client-base", tags=["client-base"])


@router.get("/dashboard")
async def dashboard(
    period: str = Query("month", description="day|week|month|quarter|year"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await client_base.build_dashboard(db, period)


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


@router.get("/clients")
async def clients_by_segment(
    segment: str = Query(..., description="active|due|risk|late|lost"),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    return await client_base.get_clients_by_segment(db, segment)


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
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    return await client_base.get_tasks(db, status)


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
    return await client_base.record_outcome(db, task_id, outcome, channel, comment, actor_id)


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
async def journal_download() -> FileResponse:
    path = call_journal.journal_path()
    if not path.exists():
        raise HTTPException(status_code=404, detail="Журнал пока пуст: не было ни одного звонка")
    return FileResponse(
        path,
        filename=call_journal.JOURNAL_NAME,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
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
async def journal_import(request: Request, file: UploadFile = File(...)) -> dict:
    """Влить журнал прошлой установки. Строки дописываются, дубли пропускаются."""
    _require_owner(request)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix != ".xlsx":
        raise HTTPException(status_code=400, detail="Нужен файл .xlsx")

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(await file.read())
        temp_path = Path(tmp.name)
    try:
        return call_journal.merge_journal(temp_path)
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
