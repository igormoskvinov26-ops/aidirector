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
from app.services import cache, configuration

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


def непустой(что: str, данные: list[Any]) -> None:
    """Пустой справочник — это отказ адреса, а не «ничего не изменилось».

    У работающего барбершопа не бывает ноль сотрудников или ноль услуг. Если
    YCLIENTS прислал пустоту, прежние данные в базе остаются нетронутыми, но
    на экране должна стоять причина, а не молчаливый ноль: именно так
    выглядела бы потеря прав у токена, и заметить её было бы нечем.
    """
    if not данные:
        raise RuntimeError(
            f"YCLIENTS вернул пустой список: {что}. Чаще всего это значит, что "
            "у пользовательского токена отозваны права или он выдан на другой филиал."
        )


async def sync_all(
    date_from: str | None = None, date_to: str | None = None
) -> dict[str, Any]:
    """Pull YCLIENTS -> PostgreSQL for a bounded window.

    When no dates are given the window defaults to ``default_window()``. The
    previous version passed None straight through, which made every sync
    re-download the entire history.

    Шаги идут каждый в своей обёртке. Прежде выгрузка была «всё или ничего»:
    отказ на первом же шаге — сотрудниках — отменял и визиты, и продажи, хотя
    те могли бы обновиться. Теперь упавший шаг не мешает остальным, а прогон
    в целом помечается неудачным с перечислением того, что не прошло.
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

    # Пока ключи не заведены, ходить некуда. Отдельная ветка, а не отказ
    # внутри шага: иначе каждый час в журнал ложился бы неудачный прогон с
    # ошибкой авторизации, и настоящие отказы утонули бы среди них.
    if not configuration.настроена("yclients"):
        logger.info("YCLIENTS не настроен — выгрузка пропущена")
        return {
            "status": "skipped",
            "reason": "not_configured",
            "error": "YCLIENTS не настроен — заполните ключи в разделе "
            "«Настройки → Интеграции»",
        }

    _sync_in_progress = True
    _sync_stage = None
    начало = datetime.now(UTC)
    stats: dict[str, Any] = {}
    ошибки: list[str] = []

    def сбой(шаг: str, беда: Exception) -> None:
        """Записать отказ шага так, чтобы по тексту было видно место.

        Без названия шага на экране оставалось голое «'NoneType' object is not
        iterable» — по нему нельзя понять, сотрудники это, визиты или продажи.
        """
        имя = STAGES.get(шаг, шаг)
        logger.error(f"шаг «{имя}» не прошёл: {беда}")
        ошибки.append(f"«{имя}»: {беда}")

    try:
        async with YClientsClient() as api_client:
            async with async_session() as session:
                # 1. Staff
                _sync_stage = "staff"
                try:
                    logger.info("Syncing staff...")
                    staff_data = await api_client.get_staff()
                    непустой("сотрудники", staff_data)
                    employee_ids = await EmployeeRepository.upsert_many(session, staff_data)
                    stats["staff"] = len(employee_ids)
                except Exception as беда:
                    сбой("staff", беда)

                # 2. Services
                _sync_stage = "services"
                try:
                    logger.info("Syncing services...")
                    services_data = await api_client.get_services()
                    непустой("услуги", services_data)
                    svc_count = await ServiceRepository.upsert_many(session, services_data)
                    stats["services"] = svc_count
                except Exception as беда:
                    сбой("services", беда)

                # 3. Clients
                _sync_stage = "clients"
                try:
                    logger.info("Syncing clients...")
                    clients_data = await api_client.get_all_clients()
                    client_count = await ClientRepository.upsert_many(session, clients_data)
                    stats["clients"] = client_count
                except Exception as беда:
                    сбой("clients", беда)

                # Справочники берём из базы, а не из свежего ответа: если шаг
                # выше не прошёл, соответствия всё равно нужны — из того, что
                # было выгружено раньше.
                employees = await EmployeeRepository.get_all(session)
                employee_map = {e.yclients_id: e.id for e in employees}

                clients = await ClientRepository.get_all(session)
                client_map = {c.yclients_id: c.id for c in clients}

                services = await ServiceRepository.get_all(session)
                service_map = {s.yclients_id: s.id for s in services}

                # 4. Records/Visits
                _sync_stage = "visits"
                try:
                    logger.info("Syncing visits...")
                    records_data = await api_client.get_all_records(
                        date_from=date_from, date_to=date_to
                    )
                    visit_count = await VisitRepository.upsert_many(
                        session, records_data, employee_map, client_map, service_map
                    )
                    stats["visits"] = visit_count
                except Exception as беда:
                    сбой("visits", беда)

                # 5. Products & Sales
                _sync_stage = "sales"
                try:
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
                except Exception as беда:
                    сбой("sales", беда)

        _last_sync = datetime.now()
        cache.invalidate()

        if ошибки:
            текст = "; ".join(ошибки)
            stats["error"] = текст
            logger.error(f"Sync finished with errors: {текст}")
            await _записать_прогон(начало, stats, текст)
        else:
            logger.info(f"Sync complete: {stats}")
            await _записать_прогон(начало, stats, None)

    except Exception as e:
        # Сюда попадает только то, что сломалось вне шагов: не поднялся клиент
        # или недоступна база. Шаг, на котором это случилось, всё равно назовём.
        место = STAGES.get(_sync_stage or "", _sync_stage or "подготовка")
        текст = f"«{место}»: {e}"
        logger.error(f"Sync failed: {текст}")
        stats["error"] = текст
        await _записать_прогон(начало, stats, текст)

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

    предел = max(1, settings.sync_timeout_minutes) * 60
    logger.info(f"Auto-sync scheduler started (every {interval} min, limit {предел // 60} min)")
    await asyncio.sleep(10)  # let the app finish startup before the first run

    while True:
        начало = datetime.now(UTC)
        try:
            # Предел на прогон. Прежде зависший ответ YCLIENTS оставлял флаг
            # «идёт выгрузка» поднятым навсегда, и все следующие запуски по
            # расписанию молча пропускались — данные переставали обновляться,
            # а в журнале не было ни одной ошибки, только тишина.
            stats = await asyncio.wait_for(sync_all(), timeout=предел)
            logger.info(f"Auto-sync finished: {stats}")
            await refresh_client_base()
            await _проверить_обзвон()
        except TimeoutError:
            текст = f"выгрузка не уложилась в {предел // 60} мин и была прервана"
            logger.error(f"Auto-sync timed out: {текст}")
            await _записать_прогон(начало, {}, текст)
        except Exception as e:
            logger.error(f"Auto-sync failed: {e}")
            await _записать_прогон(начало, {}, str(e))
        await asyncio.sleep(interval * 60)


async def _проверить_обзвон() -> None:
    """Повторно проверить звонки «Записан» в YCLIENTS после выгрузки.

    Сбой проверки не должен ронять цикл синхронизации: звонки просто
    остаются в ожидании до следующего прохода.
    """
    from app.database import async_session
    from app.services import monthly_report

    try:
        async with async_session() as session:
            итог = await monthly_report.verify_pending(session)
        if итог["checked"]:
            logger.info(f"Проверка обзвона: {итог}")
    except Exception as exc:
        logger.warning(f"Проверка обзвона не выполнена: {exc}")


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


async def проверка_связи() -> dict[str, Any]:
    """Опросить адреса YCLIENTS по одному и показать, кто чем ответил.

    Появилась после 28.09.2026, когда обновление встало на двое суток, а
    понять причину было нечем: на экране стояла одна строка с текстом
    исключения, и чтобы узнать, какой адрес подводит, приходилось читать
    журнал контейнера. Теперь это одна кнопка: видно, где именно отказ.

    Запросы лёгкие — справочники и один сегодняшний день, без выгрузки в базу.
    """
    сегодня = date.today().isoformat()
    итог: list[dict[str, Any]] = []

    async def спросить(имя: str, зовём: Any) -> None:
        try:
            строки = await зовём()
            итог.append(
                {
                    "адрес": имя,
                    "ок": True,
                    "строк": len(строки) if isinstance(строки, list) else 1,
                    "ошибка": None,
                }
            )
        except Exception as беда:
            итог.append({"адрес": имя, "ок": False, "строк": 0, "ошибка": str(беда)[:300]})

    try:
        async with YClientsClient() as api:
            # Кеш обходим: проверка должна показывать сегодняшнее состояние
            # связи, а не то, что успело осесть в памяти час назад.
            cache.invalidate(str(api.company_id))
            await спросить("сотрудники", api.get_staff)
            await спросить("услуги", api.get_services)
            await спросить("клиенты", api.get_all_clients)
            await спросить(
                "записи за сегодня",
                lambda: api.get_all_records(date_from=сегодня, date_to=сегодня),
            )
            await спросить(
                "продажи за сегодня",
                lambda: api.get_transactions(date_from=сегодня, date_to=сегодня),
            )
    except Exception as беда:
        return {
            "ок": False,
            "вывод": f"не удалось даже создать подключение: {беда}",
            "проверки": итог,
        }

    плохие = [п for п in итог if not п["ок"]]
    пустые = [п["адрес"] for п in итог if п["ок"] and not п["строк"] and п["адрес"] in
              ("сотрудники", "услуги")]

    if плохие:
        вывод = "Отказ: " + "; ".join(f"{п['адрес']} — {п['ошибка']}" for п in плохие)
    elif пустые:
        вывод = (
            "Связь есть, но пусто: " + ", ".join(пустые) + ". "
            "Обычно это значит, что у пользовательского токена отозваны права "
            "или он выдан на другой филиал."
        )
    else:
        вывод = "Связь в порядке, все адреса отвечают."

    return {"ок": not плохие and not пустые, "вывод": вывод, "проверки": итог}


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
