"""Структура расходов в базе вместо констант в исходнике.

Раньше расходы жили в finance.py одним числом FIXED_DAILY_COST = 11000 плюс
три процента рядом. Владелец не мог поправить аренду, не редактируя код, и не
видел, из чего складывается порог безубыточности.

Аренда взята из отчёта P&L за август 2026, доля расходников — оттуда же.
Оплата труда задана владельцем и с отчётом не сходится: там управляющий и
администратор проходят отдельными строками по 41 500 и 35 000, тогда как на
деле управляющий совмещён со вторым администратором на окладе 90 000, а
сменный администратор получает за смену. Отчёт кассовый, с переносом выплат
между месяцами, поэтому источником взяты слова владельца.

Ставка мастера 40% и гарант 4 000 за смену названы владельцем. По отчёту они
не выводятся и с ним не сходятся: в августе выплаты барберам составили 20%
от услуг, в сентябре 64%. Отчёт кассовый, выплаты смещены на месяц вперёд,
поэтому источником взяты слова владельца, а не эти доли.

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
        sa.Column("cleaning_monthly", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("taxes_monthly", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("other_fixed_monthly", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("admin_per_shift", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("admin_shifts_per_month", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("materials_pct", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("acquiring_pct", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("master_commission_pct", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("product_commission_pct", sa.Numeric(5, 2), nullable=False, server_default="0"),
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
        "manager_monthly": "90000.00",     # управляющий, совмещён со вторым админом
        "cleaning_monthly": "15000.00",    # уборка, август
        "taxes_monthly": "6000.00",        # налоги и сборы
        "other_fixed_monthly": "0.00",     # бизнес- и прочие расходы нерегулярны
        "admin_per_shift": "4000.00",       # сменный администратор, за смену
        "admin_shifts_per_month": "15.50",  # 15-16 смен, остальные — за управляющим
        "materials_pct": "3.50",           # расходники: 29 060 от 824 465 = 3,52%
        "acquiring_pct": "0.00",           # в отчёте нуль
        "master_commission_pct": "40.00",   # с услуг, подтверждено владельцем
        "product_commission_pct": "10.00",  # с косметики, требует подтверждения
    }])


    # План на месяц теперь задаётся по прибыли: выручка при разном составе
    # смены даёт разную прибыль, поэтому целью служит именно прибыль.
    op.alter_column("plan_targets", "revenue_target", new_column_name="profit_target")


def downgrade() -> None:
    op.alter_column("plan_targets", "profit_target", new_column_name="revenue_target")
    op.drop_table("cost_model")
