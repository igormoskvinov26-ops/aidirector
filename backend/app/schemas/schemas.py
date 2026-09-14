"""Pydantic schemas for API request/response models."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator


# ── Employee ──
class EmployeeResponse(BaseModel):
    id: int
    yclients_id: int
    name: str
    specialization: str | None = None
    position: str | None = None
    avatar_url: str | None = None
    rating: float | None = None
    is_active: bool

    model_config = {"from_attributes": True}


class EmployeeDetail(EmployeeResponse):
    total_visits: int = 0
    total_revenue: Decimal = Decimal("0")
    avg_check: Decimal = Decimal("0")
    product_sales: Decimal = Decimal("0")
    retention_pct: float = 0.0


# ── Client ──
class ClientResponse(BaseModel):
    id: int
    yclients_id: int
    name: str
    phone: str
    email: str | None = None
    total_visits: int
    total_spent: Decimal
    last_visit_date: datetime | None = None
    first_visit_date: datetime | None = None

    model_config = {"from_attributes": True}


class ClientDetail(ClientResponse):
    days_since_last_visit: int | None = None
    ltv: Decimal = Decimal("0")
    rfm_segment: str = "unknown"


# ── Visit ──
class VisitServiceResponse(BaseModel):
    id: int
    title: str
    quantity: int
    price: Decimal

    model_config = {"from_attributes": True}


class VisitResponse(BaseModel):
    id: int
    yclients_id: int
    client_id: int
    employee_id: int
    datetime: datetime
    length_minutes: int
    status: str
    total_amount: Decimal
    is_paid: bool
    services: list[VisitServiceResponse] = []

    model_config = {"from_attributes": True}


# ── Service ──
class ServiceResponse(BaseModel):
    id: int
    yclients_id: int
    title: str
    category: str | None = None
    price_min: Decimal
    price_max: Decimal

    model_config = {"from_attributes": True}


# ── Dashboard ──
class KPICards(BaseModel):
    total_revenue: Decimal
    avg_check: Decimal
    total_visits: int
    new_clients: int
    repeat_clients: int
    retention_pct: float
    ltv: Decimal
    cancellation_pct: float
    product_sales: Decimal
    profit: Decimal


class DailyRevenuePoint(BaseModel):
    date: str
    revenue: Decimal
    visits: int
    avg_check: Decimal


class MasterMetric(BaseModel):
    name: str
    avatar_url: str | None = None
    visits: int
    revenue: Decimal
    avg_check: Decimal
    retention_pct: float
    product_sales: Decimal


class ServiceMetric(BaseModel):
    name: str
    count: int
    revenue: Decimal
    pct_of_total: float


class DashboardResponse(BaseModel):
    period: str
    kpis: KPICards
    revenue_trend: list[DailyRevenuePoint]
    top_masters: list[MasterMetric]
    top_services: list[ServiceMetric]
    new_clients_trend: list[dict]
    cancellation_rate: float


# ── AI Report ──
class AIReportRequest(BaseModel):
    period_from: str
    period_to: str


class AIReportResponse(BaseModel):
    report: str
    insights: list[str]
    risks: list[str]
    opportunities: list[str]
    actions_tomorrow: list[str]


# ── Sync ──
class SyncStatusResponse(BaseModel):
    in_progress: bool
    last_sync: datetime | None = None
    records_synced: int = 0
    clients_synced: int = 0


# ── Finance ──
class DailyFinancePoint(BaseModel):
    date: str
    revenue: Decimal
    total_visits: int
    completed: int
    cancelled: int
    masters_count: int
    margin_rub: Decimal
    margin_pct: float
    break_even: Decimal
    costs: dict


class MonthlyFinancePoint(BaseModel):
    month: str
    days_in_month: int
    revenue: Decimal
    total_visits: int
    completed: int
    cancelled: int
    margin_rub: Decimal
    margin_pct: float
    break_even: Decimal
    costs: dict


class CostSettingsRequest(BaseModel):
    """Расходы. Постоянные — одной суммой в месяц, переменные — в процентах.

    Верхние границы стоят не для красоты: процент мастера вместе с расходниками
    выше сотни означает, что каждый заработанный рубль приносит убыток, и порог
    безубыточности перестаёт существовать.
    """

    fixed_monthly: Decimal = Field(..., ge=0)
    materials_pct: Decimal = Field(..., ge=0, le=100)
    acquiring_pct: Decimal = Field(default=0, ge=0, le=100)
    master_commission_pct: Decimal = Field(..., ge=0, le=100)
    product_commission_pct: Decimal = Field(default=0, ge=0, le=100)

    @model_validator(mode="after")
    def _variable_share_must_leave_something(self) -> "CostSettingsRequest":
        share = self.materials_pct + self.acquiring_pct + self.master_commission_pct
        if share >= 100:
            raise ValueError(
                "Расходники, эквайринг и процент мастера вместе дают "
                f"{share}% выручки. При таких условиях день не выйдет в плюс "
                "ни при какой выручке."
            )
        return self


class PlanTargetRequest(BaseModel):
    period: str = Field(..., pattern=r"^\d{4}-\d{2}$")
    profit_target: Decimal = Field(..., gt=0)
    margin_target_pct: float = Field(default=30.0, ge=0, le=100)


class PlanTargetResponse(BaseModel):
    period: str
    profit_target: float
    margin_target_pct: float
