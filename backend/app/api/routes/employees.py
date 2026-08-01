"""Employee routes — masters and administrators."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.yclients import YClientsClient
from app.database import get_db

router = APIRouter(prefix="/api/employees", tags=["employees"])


@router.get("/")
async def list_employees(db: AsyncSession = Depends(get_db)) -> list[dict]:
    try:
        from app.models.models import Employee
        from sqlalchemy import select
        result = await db.execute(
            select(Employee).where(Employee.is_active == True).order_by(Employee.name)
        )
        return [{"id": e.id, "yclients_id": e.yclients_id, "name": e.name,
                 "specialization": e.specialization, "position": e.position,
                 "avatar_url": e.avatar_url, "rating": float(e.rating) if e.rating else None,
                 "is_active": e.is_active} for e in result.scalars().all()]
    except Exception:
        async with YClientsClient() as client:
            staff = await client.get_staff()
            return [
                {
                    "id": s["id"], "yclients_id": s["id"], "name": s["name"],
                    "specialization": s.get("specialization"),
                    "position": s.get("position", {}).get("title") if isinstance(s.get("position"), dict) else s.get("position"),
                    "avatar_url": s.get("avatar"),
                    "rating": s.get("rating"),
                    "is_active": True,
                }
                for s in staff
            ]


@router.get("/{employee_id}")
async def get_employee(employee_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    return {"id": employee_id, "name": f"Мастер #{employee_id}"}
