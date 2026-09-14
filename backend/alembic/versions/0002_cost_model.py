"""Структура расходов в базе вместо констант в исходнике.

Раньше расходы жили в finance.py одним числом FIXED_DAILY_COST = 11000 плюс
три процента рядом. Владелец не мог поправить аренду, не редактируя код, и не
видел, из чего складывается порог безубыточности.

Начальные значения взяты из отчёта P&L за август 2026 — единственный полный
месяц с данными. Коммунальный платёж в отчёте нулевой, поставлена оценка
владельца. Процент мастера оставлен прежним: по отчёту его вывести нельзя,
зарплата выплачивается со сдвигом относительно выручки.

Revision ID: 0002_cost_model
Revises: 0001_initial
"""

import sqlalchemy as sa

from alembic import op

revision = "0002_cost_model"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = op.create_table(
        "cost_model",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rent_monthly", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("utilities_monthly", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("manager_monthly", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("admin_monthly", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("cleaning_monthly", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("other_fixed_monthly", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("materials_pct", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("acquiring_pct", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("master_commission_pct", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("master_min_guarantee", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.bulk_insert(table, [{
        "id": 1,
        "rent_monthly": "170000.00",       # из отчёта, фиксированная
        "utilities_monthly": "15000.00",   # оценка владельца, в отчёте нуль
        "manager_monthly": "41500.00",     # управляющий, август
        "admin_monthly": "35000.00",       # администратор, август
        "cleaning_monthly": "15000.00",    # уборка, август
        "other_fixed_monthly": "0.00",     # бизнес- и прочие расходы нерегулярны
        "materials_pct": "3.50",           # расходники: 29 060 от 824 465 = 3,52%
        "acquiring_pct": "0.00",           # в отчёте нуль
        "master_commission_pct": "40.00",  # прежнее значение, требует подтверждения
        "master_min_guarantee": "4000.00",
    }])


    # План на месяц теперь задаётся по прибыли: выручка при разном составе
    # смены даёт разную прибыль, поэтому целью служит именно прибыль.
    op.alter_column("plan_targets", "revenue_target", new_column_name="profit_target")


def downgrade() -> None:
    op.alter_column("plan_targets", "profit_target", new_column_name="revenue_target")
    op.drop_table("cost_model")
