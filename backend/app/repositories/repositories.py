"""Repository pattern — data access layer."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

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


class EmployeeRepository:
    @staticmethod
    async def upsert_many(session: AsyncSession, data: list[dict]) -> list[int]:
        ids = []
        for item in data:
            stmt = pg_insert(Employee).values(
                yclients_id=item["id"],
                name=item["name"],
                specialization=item.get("specialization"),
                position=item.get("position", {}).get("title") if isinstance(item.get("position"), dict) else item.get("position"),
                avatar_url=item.get("avatar"),
                rating=item.get("rating"),
            ).on_conflict_do_update(
                index_elements=["yclients_id"],
                set_={
                    "name": item["name"],
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
        result = await session.execute(select(Employee).where(Employee.is_active == True))
        return list(result.scalars().all())


class ClientRepository:
    @staticmethod
    async def upsert_many(session: AsyncSession, data: list[dict]) -> int:
        count = 0
        for item in data:
            stmt = pg_insert(Client).values(
                yclients_id=item["id"],
                name=item.get("name", ""),
                phone=item.get("phone", ""),
                email=item.get("email"),
                birthday=item.get("birthday") or item.get("birth_date"),
                sex=item.get("sex"),
                discount=item.get("discount", 0),
                card=item.get("card"),
                comment=item.get("comment"),
                total_visits=item.get("visits_count", item.get("visits", 0)),
                total_spent=item.get("spent_sum", item.get("spent", 0)),
                last_visit_date=item.get("last_visit_date"),
                first_visit_date=item.get("first_visit_date") or item.get("created_at"),
                updated_at=func.now(),
            ).on_conflict_do_update(
                index_elements=["yclients_id"],
                set_={
                    "name": item.get("name", ""),
                    "phone": item.get("phone", ""),
                    "email": item.get("email"),
                    "total_visits": item.get("visits_count", item.get("visits", 0)),
                    "total_spent": item.get("spent_sum", item.get("spent", 0)),
                    "last_visit_date": item.get("last_visit_date"),
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


class VisitRepository:
    @staticmethod
    async def upsert_many(session: AsyncSession, data: list[dict], employee_map: dict[int, int], client_map: dict[int, int]) -> int:
        count = 0
        for item in data:
            client_db_id = client_map.get(item.get("client", {}).get("id", 0))
            employee_db_id = employee_map.get(item.get("staff_id", 0))
            if not client_db_id or not employee_db_id:
                continue

            total_amount = Decimal("0")
            for svc in item.get("services", []):
                total_amount += Decimal(str(svc.get("cost", 0)))

            stmt = pg_insert(Visit).values(
                yclients_id=item["id"],
                client_id=client_db_id,
                employee_id=employee_db_id,
                datetime=item.get("datetime"),
                length_minutes=int((item.get("seance_length") or item.get("length", 0)) / 60),
                status=item.get("status", item.get("visit_attendance", "unknown")),
                comment=item.get("comment"),
                total_amount=total_amount,
                paid_amount=Decimal(str(item.get("paid_full", 0))),
                is_paid=bool(item.get("paid_full", 0)),
                is_new_client=item.get("client", {}).get("is_new", False),
            ).on_conflict_do_update(
                index_elements=["yclients_id"],
                set_={
                    "status": item.get("status", item.get("visit_attendance", "unknown")),
                    "total_amount": total_amount,
                    "paid_amount": Decimal(str(item.get("paid_full", 0))),
                    "is_paid": bool(item.get("paid_full", 0)),
                },
            ).returning(Visit.id)
            result = await session.execute(stmt)
            visit_row = result.fetchone()
            if not visit_row:
                continue

            visit_db_id = visit_row[0]

            for svc in item.get("services", []):
                svc_stmt = pg_insert(VisitService).values(
                    visit_id=visit_db_id,
                    service_id=svc.get("id", 0),
                    title=svc.get("title", ""),
                    quantity=svc.get("amount", 1),
                    price=Decimal(str(svc.get("cost", 0))),
                    discount=Decimal(str(svc.get("discount", 0))),
                ).on_conflict_do_nothing()
                await session.execute(svc_stmt)

            count += 1

        await session.commit()
        return count


class ServiceRepository:
    @staticmethod
    async def upsert_many(session: AsyncSession, data: list[dict]) -> int:
        count = 0
        for item in data:
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
