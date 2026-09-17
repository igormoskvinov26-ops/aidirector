"""Data synchronization service — pulls YCLIENTS → PostgreSQL."""

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.yclients import YClientsClient
from app.database import async_session
from app.repositories.repositories import (
    ClientRepository,
    EmployeeRepository,
    ProductRepository,
    SaleRepository,
    ServiceRepository,
    VisitRepository,
)
from app.services import cache

_sync_in_progress = False
_last_sync: datetime | None = None

# Какой шаг выгрузки идёт прямо сейчас. Нужно для надписи на экране: «идёт
# загрузка» без уточнения не отличает живой процесс от зависшего, а шаг
# клиентов на базе барбершопа занимает минуты.
_sync_stage: str | None = None

# Названия шагов по-русски: строку читает владелец, а не программа.
STAGES = {
    "staff": "сотрудники",
    "services": "услуги",
    "clients": "клиенты",
    "visits": "визиты",
    "sales": "продажи и товары",
    "segments": "пересчёт сегментов",
}


async def _записать_прогон(
    начало: datetime,
    статистика: dict[str, Any],
    ошибка: str | None,
) -> None:
    """Отметить выгрузку в базе.

    Пишется и удачная, и упавшая: по одной удачной не видно, что последние
    пять попыток подряд не прошли, — а это и означает, что цифры на экране
    устарели.

    Своё исключение здесь глушится намеренно: не записанная отметка — досадно,
    но уронить из-за неё уже привезённые данные нельзя.
    """
    from app.models.models import SyncRun

    try:
        async with async_session() as session:
            session.add(
                SyncRun(
                    started_at=начало,
                    finished_at=datetime.now(UTC),
                    ok=ошибка is None,
                    error=(ошибка or None) and ошибка[:500],
                    staff_count=int(статистика.get("staff") or 0),
                    services_count=int(статистика.get("services") or 0),
                    clients_count=int(статистика.get("clients") or 0),
                    visits_count=int(статистика.get("visits") or 0),
                    sales_count=int(статистика.get("sales") or 0),
                )
            )
            await session.commit()
    except Exception as сбой:
        logger.error(f"не удалось записать отметку о выгрузке: {сбой}")


def default_window(today: date | None = None) -> tuple[str, str]:
    """Окно выгрузки по умолчанию: назад за историей, вперёд за записями.

    Вперёд — обязательно. Прежняя версия заканчивала окно сегодняшним днём,
    и записи на завтра в базу не попадали вовсе: раздел предстоящих читает
    их оттуда, а не из YCLIENTS, и оставался пустым при исправной выгрузке.
    """
    from app.config import settings

    today = today or date.today()
    back = today - timedelta(days=settings.sync_window_days)
    ahead = today + timedelta(days=settings.sync_window_ahead_days)
    return back.isoformat(), ahead.isoformat()


async def sync_all(date_from: str | None = None, date_to: str | None = None) -> dict[str, int]:
    """Pull YCLIENTS -> PostgreSQL for a bounded window.

    When no dates are given the window defaults to ``default_window()``. The
    previous version passed None straight through, which made every sync
    re-download the entire history.
    """
    global _sync_in_progress, _last_sync, _sync_stage

    окно_назад, окно_вперёд = default_window()
    if date_from is None:
        date_from = окно_назад
    if date_to is None:
        date_to = окно_вперёд

    if _sync_in_progress:
        logger.info("Sync already in progress, skipping")
        return {"status": "skipped", "reason": "already_running"}

    _sync_in_progress = True
    _sync_stage = None
    начало = datetime.now(UTC)
    stats: dict[str, int] = {}

    try:
        async with YClientsClient() as api_client:
            async with async_session() as session:
                # 1. Staff
                _sync_stage = "staff"
                logger.info("Syncing staff...")
                staff_data = await api_client.get_staff()
                employee_ids = await EmployeeRepository.upsert_many(session, staff_data)
                stats["staff"] = len(employee_ids)

                # 2. Services
                _sync_stage = "services"
                logger.info("Syncing services...")
                services_data = await api_client.get_services()
                svc_count = await ServiceRepository.upsert_many(session, services_data)
                stats["services"] = svc_count

                # 3. Clients
                _sync_stage = "clients"
                logger.info("Syncing clients...")
                clients_data = await api_client.get_all_clients()
                client_count = await ClientRepository.upsert_many(session, clients_data)
                stats["clients"] = client_count

                # 4. Records/Visits
                _sync_stage = "visits"
                logger.info("Syncing visits...")
                records_data = await api_client.get_all_records(
                    date_from=date_from, date_to=date_to
                )

                employees = await EmployeeRepository.get_all(session)
                employee_map = {e.yclients_id: e.id for e in employees}

                clients = await ClientRepository.get_all(session)
                client_map = {c.yclients_id: c.id for c in clients}

                services = await ServiceRepository.get_all(session)
                service_map = {s.yclients_id: s.id for s in services}

                visit_count = await VisitRepository.upsert_many(
                    session, records_data, employee_map, client_map, service_map
                )
                stats["visits"] = visit_count

                # 5. Products & Sales
                _sync_stage = "sales"
                logger.info("Syncing products & sales...")
                transactions_data = await api_client.get_transactions(
                    date_from=date_from, date_to=date_to
                )

                products_set: dict[int, dict] = {}
                for t in transactions_data:
                    g = t.get("good") or {}
                    if g.get("id"):
                        products_set[g["id"]] = g

                await ProductRepository.upsert_many(session, list(products_set.values()))

                product_map = {}
                for p in await ProductRepository.get_all(session):
                    product_map[p.yclients_id] = p.id

                sale_count = await SaleRepository.upsert_many(
                    session, transactions_data, employee_map, client_map, product_map
                )
                stats["sales"] = sale_count

        _last_sync = datetime.now()
        cache.invalidate()
        logger.info(f"Sync complete: {stats}")
        await _записать_прогон(начало, stats, None)

    except Exception as e:
        logger.error(f"Sync failed: {e}")
        stats["error"] = str(e)
        await _записать_прогон(начало, stats, str(e))

    finally:
        _sync_in_progress = False
        _sync_stage = None

    return stats


async def run_sync_loop(interval_minutes: int | None = None) -> None:
    """Periodically run sync_all in the background.

    interval_minutes overrides settings.sync_interval_minutes; <= 0 disables the loop.
    """
    from app.config import settings

    interval = settings.sync_interval_minutes if interval_minutes is None else interval_minutes
    if interval <= 0:
        logger.info("Auto-sync disabled (sync_interval_minutes <= 0)")
        return

    logger.info(f"Auto-sync scheduler started (every {interval} min)")
    await asyncio.sleep(10)  # let the app finish startup before the first run

    while True:
        try:
            stats = await sync_all()
            logger.info(f"Auto-sync finished: {stats}")
            await refresh_client_base()
        except Exception as e:
            logger.error(f"Auto-sync failed: {e}")
        await asyncio.sleep(interval * 60)


async def refresh_client_base() -> None:
    """Recompute client segments, write today's snapshot and refresh the contact queue."""
    global _sync_stage

    _sync_stage = "segments"
    try:
        from app.services import client_base

        async with async_session() as session:
            await client_base.write_snapshot(session)
            await client_base.refresh_tasks(session)
        logger.info("Client-base snapshot + queue refreshed")
    except Exception as e:
        logger.error(f"Client-base refresh failed: {e}")
    finally:
        _sync_stage = None


def get_sync_status() -> dict[str, Any]:
    """Состояние в памяти процесса: идёт ли выгрузка и какой шаг.

    Без обращения к базе — вызывается часто и должно быть дешёвым.
    """
    return {
        "in_progress": _sync_in_progress,
        "stage": STAGES.get(_sync_stage or "") or None,
        "last_sync": _last_sync.isoformat() if _last_sync else None,
    }


async def get_sync_state(session: AsyncSession) -> dict[str, Any]:
    """Полное состояние для экрана: и текущий ход, и время обновления данных.

    Время берётся из базы, а не из памяти: после перезапуска Директора память
    пуста, и на экране стояло бы «никогда» при свежих данных.

    Различаются последняя удачная выгрузка и последняя попытка. Если попытка
    новее удачной — цифры на экране устарели, и человек должен это видеть, а
    не смотреть на вчерашние числа как на сегодняшние.
    """
    from app.models.models import SyncRun

    состояние = get_sync_status()
    состояние["last_success_at"] = None
    состояние["last_attempt_at"] = None
    состояние["last_error"] = None
    состояние["counts"] = None

    try:
        удачная = (
            await session.execute(
                select(SyncRun).where(SyncRun.ok.is_(True)).order_by(SyncRun.id.desc()).limit(1)
            )
        ).scalar_one_or_none()
        последняя = (
            await session.execute(select(SyncRun).order_by(SyncRun.id.desc()).limit(1))
        ).scalar_one_or_none()
    except Exception as сбой:
        # Таблицы может не быть, если миграции не прогонялись. Показать экран
        # без отметки лучше, чем не показать экран.
        logger.warning(f"состояние выгрузки недоступно: {сбой}")
        return состояние

    if удачная is not None:
        состояние["last_success_at"] = удачная.finished_at.isoformat()
        состояние["counts"] = {
            "staff": удачная.staff_count,
            "services": удачная.services_count,
            "clients": удачная.clients_count,
            "visits": удачная.visits_count,
            "sales": удачная.sales_count,
        }
    if последняя is not None:
        состояние["last_attempt_at"] = последняя.finished_at.isoformat()
        if not последняя.ok:
            состояние["last_error"] = последняя.error
    return состояние
