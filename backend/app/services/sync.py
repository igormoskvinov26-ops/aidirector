"""Data synchronization service — pulls YCLIENTS → PostgreSQL."""

from datetime import datetime
from typing import Any

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.yclients import YClientsClient
from app.database import async_session
from app.repositories.repositories import (
    ClientRepository,
    EmployeeRepository,
    ServiceRepository,
    VisitRepository,
)

_sync_in_progress = False
_last_sync: datetime | None = None


async def sync_all(date_from: str | None = None, date_to: str | None = None) -> dict[str, int]:
    global _sync_in_progress, _last_sync

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

                visit_count = await VisitRepository.upsert_many(
                    session, records_data, employee_map, client_map
                )
                stats["visits"] = visit_count

        _last_sync = datetime.now()
        logger.info(f"Sync complete: {stats}")

    except Exception as e:
        logger.error(f"Sync failed: {e}")
        stats["error"] = str(e)

    finally:
        _sync_in_progress = False

    return stats


def get_sync_status() -> dict[str, Any]:
    return {
        "in_progress": _sync_in_progress,
        "last_sync": _last_sync.isoformat() if _last_sync else None,
    }
