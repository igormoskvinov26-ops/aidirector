"""SQLAlchemy ORM models for Rubl AI Director."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(primary_key=True)
    yclients_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    specialization: Mapped[str | None] = mapped_column(String(255))
    position: Mapped[str | None] = mapped_column(String(100))
    avatar_url: Mapped[str | None] = mapped_column(Text)
    rating: Mapped[float | None] = mapped_column(Numeric(3, 1))
    reviews_count: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    visits: Mapped[list["Visit"]] = relationship(back_populates="employee")
    sales: Mapped[list["Sale"]] = relationship(back_populates="employee")


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    yclients_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str] = mapped_column(String(20), index=True)
    email: Mapped[str | None] = mapped_column(String(255))
    birthday: Mapped[date | None] = mapped_column(Date)
    sex: Mapped[str | None] = mapped_column(String(10))
    discount: Mapped[int] = mapped_column(Integer, default=0)
    card: Mapped[str | None] = mapped_column(String(50))
    comment: Mapped[str | None] = mapped_column(Text)
    total_visits: Mapped[int] = mapped_column(Integer, default=0)
    total_spent: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    last_visit_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_visit_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    visits: Mapped[list["Visit"]] = relationship(back_populates="client")
    sales: Mapped[list["Sale"]] = relationship(back_populates="client")


class Service(Base):
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(primary_key=True)
    yclients_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    category: Mapped[str | None] = mapped_column(String(100))
    price_min: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    price_max: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    duration: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    visits: Mapped[list["VisitService"]] = relationship(back_populates="service")


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    yclients_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    category: Mapped[str | None] = mapped_column(String(100))
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    stock: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    sale_items: Mapped[list["SaleItem"]] = relationship(back_populates="product")


class Visit(Base):
    __tablename__ = "visits"

    id: Mapped[int] = mapped_column(primary_key=True)
    yclients_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    length_minutes: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="completed")
    comment: Mapped[str | None] = mapped_column(Text)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    is_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    is_new_client: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    client: Mapped["Client"] = relationship(back_populates="visits")
    employee: Mapped["Employee"] = relationship(back_populates="visits")
    services: Mapped[list["VisitService"]] = relationship(back_populates="visit")
    sales: Mapped[list["Sale"]] = relationship(back_populates="visit")


class VisitService(Base):
    __tablename__ = "visit_services"

    id: Mapped[int] = mapped_column(primary_key=True)
    visit_id: Mapped[int] = mapped_column(ForeignKey("visits.id"), index=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"))
    title: Mapped[str] = mapped_column(String(255))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    discount: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)

    visit: Mapped["Visit"] = relationship(back_populates="services")
    service: Mapped["Service"] = relationship(back_populates="visits")


class Sale(Base):
    __tablename__ = "sales"

    id: Mapped[int] = mapped_column(primary_key=True)
    yclients_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    visit_id: Mapped[int | None] = mapped_column(ForeignKey("visits.id"), index=True)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id"), index=True)
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), index=True)
    datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    visit: Mapped["Visit | None"] = relationship(back_populates="sales")
    client: Mapped["Client | None"] = relationship(back_populates="sales")
    employee: Mapped["Employee | None"] = relationship(back_populates="sales")
    items: Mapped[list["SaleItem"]] = relationship(back_populates="sale")


class SaleItem(Base):
    __tablename__ = "sale_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))
    title: Mapped[str] = mapped_column(String(255))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)

    sale: Mapped["Sale"] = relationship(back_populates="items")
    product: Mapped["Product | None"] = relationship(back_populates="sale_items")


class DailyMetrics(Base):
    __tablename__ = "daily_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id"), index=True
    )

    total_revenue: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    total_visits: Mapped[int] = mapped_column(Integer, default=0)
    avg_check: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    new_clients: Mapped[int] = mapped_column(Integer, default=0)
    repeat_clients: Mapped[int] = mapped_column(Integer, default=0)
    cancelled: Mapped[int] = mapped_column(Integer, default=0)
    no_show: Mapped[int] = mapped_column(Integer, default=0)
    product_sales: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    utilization_pct: Mapped[Decimal] = mapped_column(Numeric(5, 1), default=0)

    __table_args__ = (
        UniqueConstraint("date", "employee_id", name="uq_daily_metrics_date_employee"),
    )


class MonthlyMetrics(Base):
    __tablename__ = "monthly_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    period: Mapped[str] = mapped_column(String(7), index=True)  # "2026-07"
    employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id"), index=True
    )

    total_revenue: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    total_visits: Mapped[int] = mapped_column(Integer, default=0)
    avg_check: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    new_clients: Mapped[int] = mapped_column(Integer, default=0)
    retention_pct: Mapped[Decimal] = mapped_column(Numeric(5, 1), default=0)
    ltv: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    cancellation_pct: Mapped[Decimal] = mapped_column(Numeric(5, 1), default=0)
    product_sales: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    fot: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    expenses: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    profit: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)

    __table_args__ = (
        UniqueConstraint("period", "employee_id", name="uq_monthly_metrics_period_employee"),
    )


class PlanTarget(Base):
    """План на месяц — по прибыли, а не по выручке.

    Выручка сама по себе ничего не говорит: при трёх мастерах на смене её
    нужно заметно больше, чтобы получить ту же прибыль. Поэтому владелец
    задаёт прибыль, а нужная выручка считается от состава смены.
    """

    __tablename__ = "plan_targets"

    id: Mapped[int] = mapped_column(primary_key=True)
    period: Mapped[str] = mapped_column(String(7), unique=True, index=True)
    profit_target: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    margin_target_pct: Mapped[Decimal] = mapped_column(Numeric(5, 1), default=30.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CostModel(Base):
    """Структура расходов барбершопа — одна актуальная строка.

    Раньше расходы были зашиты в исходник одним числом «11 000 ₽ в день».
    Владелец не мог поправить аренду, не трогая код, и не видел, из чего
    число складывается. Здесь оно разложено на составляющие: постоянные
    задаются суммой в месяц, переменные — долей от выручки.
    """

    __tablename__ = "cost_model"

    id: Mapped[int] = mapped_column(primary_key=True)

    # -- Постоянные расходы, рублей в месяц --
    rent_monthly: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    utilities_monthly: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    # Управляющий совмещён со вторым администратором, оклад фиксированный.
    manager_monthly: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    cleaning_monthly: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    taxes_monthly: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    other_fixed_monthly: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)

    # -- Сменный администратор --
    # Получает за смену, а не окладом, и выходит примерно через день:
    # остальные смены закрывает управляющий, который сидит на фиксе выше.
    # Поэтому нужны оба числа — иначе оплата размажется на все дни месяца
    # и расходы окажутся вдвое выше настоящих.
    admin_per_shift: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    admin_shifts_per_month: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)

    # -- Переменные расходы, доля от выручки в процентах --
    materials_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    acquiring_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)

    # -- Оплата мастера: проценты одинаковы для всех, поэтому живут здесь --
    master_commission_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    product_commission_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    # Гаранты у мастеров разные и задаются пофамильно в настройках барберов.
    # Держать их ещё и здесь значит однажды поправить в одном месте и забыть
    # про другое.

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ContactTask(Base):
    __tablename__ = "contact_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    group_code: Mapped[str] = mapped_column(String(40))
    priority: Mapped[int] = mapped_column(Integer, default=0)
    due_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(20), default="open")
    script_version: Mapped[str] = mapped_column(String(40), default="v1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "client_id", "group_code", "due_date", name="uq_contact_task_client_group_date"
        ),
    )


class ContactAttempt(Base):
    __tablename__ = "contact_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("contact_tasks.id"), index=True)
    outcome: Mapped[str] = mapped_column(String(20))  # booked | no_booking | no_answer
    channel: Mapped[str] = mapped_column(String(20))  # phone | message
    comment: Mapped[str | None] = mapped_column(Text)
    actor_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DailySegmentSnapshot(Base):
    __tablename__ = "daily_segment_snapshots"

    snapshot_date: Mapped[date] = mapped_column(Date, primary_key=True)
    segment_code: Mapped[str] = mapped_column(String(40), primary_key=True)
    clients_count: Mapped[int] = mapped_column(Integer, default=0)
