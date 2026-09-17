"""Data synchronization service — pulls YCLIENTS → PostgreSQL."""

import asyncio
from datetime import date, datetime, timedelta
from typing import Any

from loguru import logger

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
    global _sync_in_progress, _last_sync

    окно_назад, окно_вперёд = default_window()
    if date_from is None:
        date_from = окно_назад
    if date_to is None:
        date_to = окно_вперёд

    if _sync_in_progress:
        logger.info("Sync already in progress, skipping")
        return {"status": "skipped", "reason": "already_running"}

    _sync_in_progress = True
    stats: dict[str, int] = {}

    try:
        async with YClientsClient() as api_client:
            async with async_session() as session:
                # 1. Staff
                logger.info("Syncing staff...")
                staff_data = await api_client.get_staff()
                employee_ids = await EmployeeRepository.upsert_many(session, staff_data)
                stats["staff"] = len(employee_ids)

                # 2. Services
                logger.info("Syncing services...")
                services_data = await api_client.get_services()
                svc_count = await ServiceRepository.upsert_many(session, services_data)
                stats["services"] = svc_count

                # 3. Clients
                logger.info("Syncing clients...")
                clients_data = await api_client.get_all_clients()
                client_count = await ClientRepository.upsert_many(session, clients_data)
                stats["clients"] = client_count

                # 4. Records/Visits
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

    except Exception as e:
        logger.error(f"Sync failed: {e}")
        stats["error"] = str(e)

    finally:
        _sync_in_progress = False

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
    try:
        from app.services import client_base

        async with async_session() as session:
            await client_base.write_snapshot(session)
            await client_base.refresh_tasks(session)
        logger.info("Client-base snapshot + queue refreshed")
    except Exception as e:
        logger.error(f"Client-base refresh failed: {e}")


def get_sync_status() -> dict[str, Any]:
    return {
        "in_progress": _sync_in_progress,
        "last_sync": _last_sync.isoformat() if _last_sync else None,
    }
