"""Repository pattern — data access layer."""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from loguru import logger
from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    Client,
    DailyMetrics,
    Employee,
    MonthlyMetrics,
    Product,
    Sale,
    SaleItem,
    Service,
    Visit,
    VisitService,
)


def _parse_date(val: Any) -> date | None:
    if val is None:
        return None
    if isinstance(val, date):
        return val
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, str):
        val = val.strip()
        if not val or val.startswith("0001") or val.startswith("1900") or val.startswith("1899"):
            return None
        for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(val, fmt).date()
            except ValueError:
                continue
    return None


class EmployeeRepository:
    @staticmethod
    async def upsert_many(session: AsyncSession, data: list[dict]) -> list[int]:
        ids = []
        for item in data or []:
            # Одна битая строка из API не должна ронять весь шаг: у записи
            # без идентификатора нечего обновлять, и место ей — в журнале.
            if not isinstance(item, dict) or item.get("id") is None:
                logger.warning(f"пропущена строка без id: {str(item)[:120]}")
                continue
            stmt = pg_insert(Employee).values(
                yclients_id=item["id"],
                name=item.get("name") or f"ID {item['id']}",
                specialization=item.get("specialization"),
                position=item.get("position", {}).get("title") if isinstance(item.get("position"), dict) else item.get("position"),
                avatar_url=item.get("avatar"),
                rating=item.get("rating"),
            ).on_conflict_do_update(
                index_elements=["yclients_id"],
                set_={
                    "name": item.get("name") or f"ID {item['id']}",
                    "specialization": item.get("specialization"),
                    "avatar_url": item.get("avatar"),
                    "rating": item.get("rating"),
                    "updated_at": func.now(),
                },
            ).returning(Employee.id)
            result = await session.execute(stmt)
            row = result.fetchone()
            if row:
                ids.append(row[0])
        await session.commit()
        return ids

    @staticmethod
    async def get_all(session: AsyncSession) -> list[Employee]:
        result = await session.execute(select(Employee).where(Employee.is_active.is_(True)))
        return list(result.scalars().all())


class ClientRepository:
    @staticmethod
    async def upsert_many(session: AsyncSession, data: list[dict]) -> int:
        count = 0
        for item in data or []:
            # Одна битая строка из API не должна ронять весь шаг: у записи
            # без идентификатора нечего обновлять, и место ей — в журнале.
            if not isinstance(item, dict) or item.get("id") is None:
                logger.warning(f"пропущена строка без id: {str(item)[:120]}")
                continue
            birthday = _parse_date(item.get("birthday")) or _parse_date(item.get("birth_date"))
            last_visit = _parse_date(item.get("last_visit_date")) or _parse_date(item.get("last_visit"))
            first_visit = _parse_date(item.get("first_visit_date")) or _parse_date(item.get("created_at"))

            stmt = pg_insert(Client).values(
                yclients_id=item["id"],
                name=item.get("name", ""),
                phone=item.get("phone", ""),
                email=item.get("email"),
                birthday=birthday,
                sex=item.get("sex"),
                discount=item.get("discount", 0),
                card=item.get("card"),
                comment=item.get("comment"),
                total_visits=item.get("visits_count", item.get("visits", 0)),
                total_spent=item.get("spent_sum", item.get("spent", 0)),
                last_visit_date=last_visit,
                first_visit_date=first_visit,
                updated_at=func.now(),
            ).on_conflict_do_update(
                index_elements=["yclients_id"],
                set_={
                    "name": item.get("name", ""),
                    "phone": item.get("phone", ""),
                    "email": item.get("email"),
                    "total_visits": item.get("visits_count", item.get("visits", 0)),
                    "total_spent": item.get("spent_sum", item.get("spent", 0)),
                    "last_visit_date": last_visit,
                    "updated_at": func.now(),
                },
            )
            await session.execute(stmt)
            count += 1
        await session.commit()
        return count

    @staticmethod
    async def get_all(session: AsyncSession) -> list[Client]:
        result = await session.execute(select(Client))
        return list(result.scalars().all())

    @staticmethod
    async def get_by_yclients_id(session: AsyncSession, yclients_id: int) -> Client | None:
        result = await session.execute(
            select(Client).where(Client.yclients_id == yclients_id)
        )
        return result.scalars().first()


def _parse_datetime(val: Any) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        val = val.strip()
        if not val:
            return None
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(val, fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(val)
        except ValueError:
            pass
    return None


# ── Чтение полей ответа YCLIENTS ──────────────────────────────────────────
#
# YCLIENTS отличает «поля нет» от «поле есть, но пустое» и во втором случае
# присылает null. Запись item.get("client", {}) спасает только от первого:
# при "client": null get возвращает None, и следующий .get(...) роняет весь
# шаг. Так 28.09.2026 в 16:41 и встала выгрузка визитов — на одной записи
# без клиента (перерыв мастера или гость без записи), и двое суток данные
# не обновлялись. Эти четыре функции — единственный способ читать такие поля.


def _словарь(значение: Any) -> dict:
    """Вложенный объект или пустой словарь — для null, строки, числа."""
    return значение if isinstance(значение, dict) else {}


def _записи(значение: Any) -> list[dict]:
    """Список объектов без null и мусора внутри. null целиком — пустой список."""
    if not isinstance(значение, list):
        return []
    return [x for x in значение if isinstance(x, dict)]


def _деньги(значение: Any) -> Decimal:
    """Сумма из ответа. null, пустая строка и мусор — ноль, а не падение шага."""
    if значение is None or значение == "":
        return Decimal("0")
    try:
        return Decimal(str(значение))
    except (InvalidOperation, ValueError):
        logger.warning(f"сумма не разобрана, считаю нулём: {str(значение)[:40]}")
        return Decimal("0")


def _целое(значение: Any) -> int:
    """Целое из ответа. null и мусор — ноль."""
    try:
        return int(значение or 0)
    except (TypeError, ValueError):
        return 0


def _visit_amount(services: list[dict]) -> Decimal:
    """Сумма визита по его строкам услуг.

    cost_to_pay — сумма к оплате, cost — по прайсу без учёта скидки; они
    расходятся ровно тогда, когда на визит есть скидка. app/services/
    barber_month.py на том же ответе YCLIENTS уже берёт cost_to_pay первым —
    правило оттуда: раньше здесь брался только cost, и выручка визита со
    скидкой в базу уходила завышенной, а эти два места считали одно и то же
    по-разному.
    """
    total = Decimal("0")
    for svc in _записи(services):
        value = next(
            (svc[k] for k in ("cost_to_pay", "cost", "first_cost") if svc.get(k) is not None),
            0,
        )
        total += _деньги(value)
    return total


def _normalize_visit_status(raw: Any) -> str:
    """Код посещения YCLIENTS в наш статус.

    В YCLIENTS visit_attendance принимает четыре значения: 1 — пришёл,
    2 — подтвердил, 0 — ожидание, -1 — не пришёл. Раньше сюда же сваливались
    отмены и неявки, и всё это становилось «запланировано». В итоге неявка
    прошлой недели навсегда оставалась будущим доходом: на графике её рисовало
    контуром как запись, которая ещё принесёт деньги.

    Теперь несостоявшийся визит отличается от предстоящего. Деньги по нему не
    придут, и складывать его с записями на завтра нельзя.
    """
    status_str = str(raw).lower() if raw is not None else "unknown"
    if status_str in ("1", "completed", "finished", "attended", "visit"):
        return "completed"
    if status_str in ("-1", "noshow", "no_show", "no show", "unattended"):
        return "no_show"
    if status_str in ("canceled", "cancelled", "deleted"):
        return "cancelled"
    # 2 — подтверждена, 0 — ожидает подтверждения. И то и другое впереди.
    return "scheduled"


async def _услуга_под_ссылку(
    session: AsyncSession,
    service_map: dict[int, int],
    svc: dict,
) -> int | None:
    """Локальный id услуги. Для незнакомой — завести запись-заместитель.

    YCLIENTS отдаёт список действующих услуг, а визиты за прошедшие месяцы
    ссылаются и на удалённые: три месяца истории почти наверняка содержат
    услугу, которую с тех пор убрали из прейскуранта.

    Прежде в ссылку подставлялся идентификатор услуги из YCLIENTS — чужое для
    нашей базы число. Отсюда две беды. База отвергала ссылку и вместе с ней
    всю выгрузку визитов: на живой установке 2441 визит приехал и не сохранился
    ни один. А совпади это число со существующей строкой услуг — визит молча
    приписался бы не к той услуге, и ошибка уехала бы в расчёт зарплаты.

    Заместитель помечается неактивным: это не услуга прейскуранта, а след
    удалённой. Название и цена строки визита сохраняются как были.
    """
    yclients_id = svc.get("id")
    if not yclients_id:
        return None
    if yclients_id in service_map:
        return service_map[yclients_id]

    название = (svc.get("title") or "").strip() or "Услуга удалена в YCLIENTS"
    stmt = (
        pg_insert(Service)
        .values(yclients_id=yclients_id, title=название[:255], is_active=False)
        # Обновление-пустышка нужно ради RETURNING: do_nothing на конфликте
        # не возвращает строку, и id пришлось бы запрашивать отдельно.
        .on_conflict_do_update(
            index_elements=["yclients_id"], set_={"yclients_id": yclients_id}
        )
        .returning(Service.id)
    )
    строка = (await session.execute(stmt)).fetchone()
    if строка is None:
        return None
    service_map[yclients_id] = строка[0]
    return строка[0]


class VisitRepository:
    @staticmethod
    async def upsert_many(
        session: AsyncSession,
        data: list[dict],
        employee_map: dict[int, int],
        client_map: dict[int, int],
        service_map: dict[int, int],
    ) -> int:
        count = 0
        # Пропуски считаем и сообщаем. Молчаливое отбрасывание — то, на чём
        # этот проект уже спотыкался дважды: выгрузка обрывалась на первой
        # странице, а визиты не сохранялись из-за ссылки на услугу — и в обоих
        # случаях в журнале не было ни строчки. Разница между «приехало» и
        # «сохранено» должна быть объяснима, а не угадываема.
        без_клиента = 0
        без_мастера = 0
        без_времени = 0
        # Сами идентификаторы, а не только счёт. Без них непонятно, что это:
        # удалённый сотрудник, запись без выбора мастера (staff_id = 0) или
        # что-то третье. Лечится каждый случай по-разному, а завести под них
        # «заместителя» наугад нельзя: число мастеров в смене считается по
        # визитам, и лишний мастер поднимет порог безубыточности.
        #
        # Это номера, а не персональные данные: имён и телефонов здесь нет.
        чужие_мастера: set[int] = set()
        чужие_клиенты: set[int] = set()

        for item in data or []:
            # Одна битая строка из API не должна ронять весь шаг: у записи
            # без идентификатора нечего обновлять, и место ей — в журнале.
            if not isinstance(item, dict) or item.get("id") is None:
                logger.warning(f"пропущена строка без id: {str(item)[:120]}")
                continue
            клиент = _словарь(item.get("client"))
            client_db_id = client_map.get(_целое(клиент.get("id")))
            employee_db_id = employee_map.get(_целое(item.get("staff_id")))
            if not client_db_id:
                # Законно для заблокированного времени в журнале записи: там
                # клиента нет вовсе. Но так же выглядит и клиент, которого не
                # довезла выгрузка клиентской базы, — а это уже потеря.
                без_клиента += 1
                чужие_клиенты.add(_целое(клиент.get("id")))
                continue
            if not employee_db_id:
                # Решение владельца 17.09.2026: такие визиты пропускать.
                # Это старая история, когда в салоне выходил другой мастер,
                # которого в YCLIENTS больше нет. На живой установке их 115 из
                # 2442 — выручка тех дней в план-факте занижена на эту долю.
                #
                # Заводить под них запись-заместителя НЕЛЬЗЯ, хотя для
                # удалённых услуг сделано именно так. Число мастеров в смене
                # считается по визитам (count distinct employee_id в
                # app/services/finance.py), а от него зависит порог
                # безубыточности: лишний мастер поднимет порог, и зоны на
                # графике поедут молча, без ошибки.
                #
                # На будущее таких визитов быть не должно. Если их число
                # начнёт расти — значит появился мастер, которого не довозит
                # выгрузка сотрудников, и это уже потеря сегодняшних денег.
                без_мастера += 1
                чужие_мастера.add(
                    _целое(item.get("staff_id") or _словарь(item.get("staff")).get("id"))
                )
                continue

            total_amount = _visit_amount(item.get("services"))

            raw_status = item.get("visit_attendance") if item.get("visit_attendance") is not None else item.get("status")
            normalized_status = _normalize_visit_status(raw_status)
            visit_datetime = _parse_datetime(item.get("datetime"))

            if visit_datetime is None:
                без_времени += 1
                continue

            stmt = pg_insert(Visit).values(
                yclients_id=item["id"],
                client_id=client_db_id,
                employee_id=employee_db_id,
                datetime=visit_datetime,
                length_minutes=_целое(item.get("seance_length") or item.get("length")) // 60,
                status=normalized_status,
                comment=item.get("comment"),
                total_amount=total_amount,
                paid_amount=_деньги(item.get("paid_full")),
                is_paid=bool(item.get("paid_full")),
                is_new_client=bool(клиент.get("is_new")),
            ).on_conflict_do_update(
                index_elements=["yclients_id"],
                set_={
                    "datetime": visit_datetime,
                    "status": normalized_status,
                    "total_amount": total_amount,
                    "paid_amount": _деньги(item.get("paid_full")),
                    "is_paid": bool(item.get("paid_full")),
                },
            ).returning(Visit.id)
            result = await session.execute(stmt)
            visit_row = result.fetchone()
            if not visit_row:
                continue

            visit_db_id = visit_row[0]

            for svc in _записи(item.get("services")):
                svc_db_id = await _услуга_под_ссылку(session, service_map, svc)
                if svc_db_id is None:
                    continue
                svc_stmt = pg_insert(VisitService).values(
                    visit_id=visit_db_id,
                    service_id=svc_db_id,
                    title=svc.get("title") or "",
                    quantity=_целое(svc.get("amount")) or 1,
                    price=_деньги(svc.get("cost")),
                    discount=_деньги(svc.get("discount")),
                ).on_conflict_do_nothing()
                await session.execute(svc_stmt)

            count += 1

        пропущено = без_клиента + без_мастера + без_времени
        if пропущено:
            logger.warning(
                f"визиты: приехало {len(data)}, сохранено {count}, "
                f"пропущено {пропущено} "
                f"(без клиента {без_клиента}, без мастера {без_мастера}, "
                f"без даты {без_времени})"
            )
            if чужие_мастера:
                logger.warning(
                    f"  неизвестные мастера в визитах: {sorted(чужие_мастера)}"
                )
            if чужие_клиенты:
                logger.warning(
                    f"  неизвестные клиенты в визитах: {sorted(чужие_клиенты)[:20]}"
                )

        await session.commit()
        return count


class ServiceRepository:
    @staticmethod
    async def get_all(session: AsyncSession) -> list[Service]:
        result = await session.execute(select(Service))
        return list(result.scalars().all())

    @staticmethod
    async def upsert_many(session: AsyncSession, data: list[dict]) -> int:
        count = 0
        for item in data or []:
            # Одна битая строка из API не должна ронять весь шаг: у записи
            # без идентификатора нечего обновлять, и место ей — в журнале.
            if not isinstance(item, dict) or item.get("id") is None:
                logger.warning(f"пропущена строка без id: {str(item)[:120]}")
                continue
            stmt = pg_insert(Service).values(
                yclients_id=item["id"],
                title=item.get("title", ""),
                category=item.get("category") or (item.get("category_id") and str(item.get("category_id"))),
                price_min=Decimal(str(item.get("price_min", 0))),
                price_max=Decimal(str(item.get("price_max", 0))),
                duration=item.get("duration"),
                is_active=bool(item.get("active", True)),
            ).on_conflict_do_update(
                index_elements=["yclients_id"],
                set_={
                    "title": item.get("title", ""),
                    "price_min": Decimal(str(item.get("price_min", 0))),
                    "price_max": Decimal(str(item.get("price_max", 0))),
                    "is_active": bool(item.get("active", True)),
                },
            )
            await session.execute(stmt)
            count += 1
        await session.commit()
        return count


class MetricsRepository:
    @staticmethod
    async def upsert_daily(
        session: AsyncSession,
        record_date: date,
        employee_id: int | None,
        metrics: dict,
    ) -> None:
        stmt = pg_insert(DailyMetrics).values(
            date=record_date,
            employee_id=employee_id,
            **metrics,
        ).on_conflict_do_update(
            index_elements=["date", "employee_id"],
            set_=metrics,
        )
        await session.execute(stmt)
        await session.commit()

    @staticmethod
    async def upsert_monthly(
        session: AsyncSession,
        period: str,
        employee_id: int | None,
        metrics: dict,
    ) -> None:
        stmt = pg_insert(MonthlyMetrics).values(
            period=period,
            employee_id=employee_id,
            **metrics,
        ).on_conflict_do_update(
            index_elements=["period", "employee_id"],
            set_=metrics,
        )
        await session.execute(stmt)
        await session.commit()

    @staticmethod
    async def get_daily_range(
        session: AsyncSession, date_from: date, date_to: date
    ) -> list[DailyMetrics]:
        result = await session.execute(
            select(DailyMetrics)
            .where(
                and_(
                    DailyMetrics.date >= date_from,
                    DailyMetrics.date <= date_to,
                    DailyMetrics.employee_id.is_(None),
                )
            )
            .order_by(DailyMetrics.date)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_monthly_range(
        session: AsyncSession, period_from: str, period_to: str
    ) -> list[MonthlyMetrics]:
        result = await session.execute(
            select(MonthlyMetrics)
            .where(
                and_(
                    MonthlyMetrics.period >= period_from,
                    MonthlyMetrics.period <= period_to,
                    MonthlyMetrics.employee_id.is_(None),
                )
            )
            .order_by(MonthlyMetrics.period)
        )
        return list(result.scalars().all())


class ProductRepository:
    @staticmethod
    async def upsert_many(session: AsyncSession, data: list[dict]) -> int:
        count = 0
        for item in data or []:
            # Одна битая строка из API не должна ронять весь шаг: у записи
            # без идентификатора нечего обновлять, и место ей — в журнале.
            if not isinstance(item, dict) or item.get("id") is None:
                logger.warning(f"пропущена строка без id: {str(item)[:120]}")
                continue
            stmt = pg_insert(Product).values(
                yclients_id=item["id"],
                title=item.get("title", ""),
                price=Decimal(str(item.get("cost_per_unit", item.get("price", 0)))),
            ).on_conflict_do_update(
                index_elements=["yclients_id"],
                set_={"title": item.get("title", ""), "price": Decimal(str(item.get("cost_per_unit", item.get("price", 0))))},
            )
            await session.execute(stmt)
            count += 1
        await session.commit()
        return count

    @staticmethod
    async def get_all(session: AsyncSession) -> list[Product]:
        result = await session.execute(select(Product))
        return list(result.scalars().all())


class SaleRepository:
    @staticmethod
    async def upsert_many(
        session: AsyncSession,
        data: list[dict],
        employee_map: dict[int, int],
        client_map: dict[int, int],
        product_map: dict[int, int],
    ) -> int:
        count = 0
        for item in data or []:
            # Одна битая строка из API не должна ронять весь шаг: у записи
            # без идентификатора нечего обновлять, и место ей — в журнале.
            if not isinstance(item, dict) or item.get("id") is None:
                logger.warning(f"пропущена строка без id: {str(item)[:120]}")
                continue
            tid = item.get("type_id")
            if tid not in (2, 4):
                continue

            amount = abs(_целое(item.get("amount")))
            if amount <= 0:
                continue

            client_db_id = None
            client_data = _записи(item.get("client"))
            if client_data:
                client_db_id = client_map.get(_целое(client_data[0].get("id")))

            master_db_id = None
            master_data = _записи(item.get("master"))
            if master_data:
                master_db_id = employee_map.get(_целое(master_data[0].get("id")))

            sale_datetime = _parse_datetime(item.get("create_date"))

            # Незнакомый товар — пустая ссылка, а не его номер из YCLIENTS:
            # чужое число здесь либо отвергается базой, либо указывает на
            # посторонний товар. Поле допускает пустоту, а название и цена
            # строки продажи хранятся рядом и не теряются.
            товар = _словарь(item.get("good"))
            product_yid = _целое(товар.get("id"))
            product_db_id = product_map.get(product_yid)

            sale_id = item["id"]
            sale_cost = abs(_деньги(item.get("cost")))

            stmt = pg_insert(Sale).values(
                yclients_id=sale_id,
                visit_id=None,
                client_id=client_db_id,
                employee_id=master_db_id,
                datetime=sale_datetime,
                total_amount=sale_cost,
            ).on_conflict_do_update(
                index_elements=["yclients_id"],
                set_={"total_amount": sale_cost},
            ).returning(Sale.id)

            result = await session.execute(stmt)
            row = result.fetchone()
            if not row:
                continue
            sale_db_id = row[0]

            item_stmt = pg_insert(SaleItem).values(
                sale_id=sale_db_id,
                product_id=product_db_id,
                title=товар.get("title") or "",
                quantity=amount,
                price=_деньги(item.get("cost_per_unit")),
            ).on_conflict_do_nothing()
            await session.execute(item_stmt)

            count += 1

        await session.commit()
        return count
