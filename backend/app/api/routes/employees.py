"""Employee routes — masters and administrators."""

from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.models import Employee, Visit
from app.schemas.schemas import EmployeeDetail, EmployeeResponse

router = APIRouter(prefix="/api/employees", tags=["employees"])


@router.get("/", response_model=list[EmployeeResponse])
async def list_employees(db: AsyncSession = Depends(get_db)) -> list[Employee]:
    result = await db.execute(
        select(Employee).where(Employee.is_active == True).order_by(Employee.name)
    )
    return list(result.scalars().all())


@router.get("/{employee_id}", response_model=EmployeeDetail)
async def get_employee(
    employee_id: int, db: AsyncSession = Depends(get_db)
) -> dict:
    emp = await db.get(Employee, employee_id)
    if not emp:
        return {}

    visit_stats = await db.execute(
        select(
            func.count(Visit.id).label("total_visits"),
            func.sum(Visit.total_amount).label("total_revenue"),
        ).where(Visit.employee_id == employee_id)
    )
    row = visit_stats.one_or_none()
    total_visits = row.total_visits or 0
    total_revenue = row.total_revenue or Decimal("0")

    return {
        **EmployeeResponse.model_validate(emp).model_dump(),
        "total_visits": total_visits,
        "total_revenue": total_revenue,
        "avg_check": Decimal(str(round(total_revenue / total_visits, 2))) if total_visits > 0 else Decimal("0"),
        "product_sales": Decimal("0"),
        "retention_pct": 0.0,
    }
