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

Условия оплаты мастера названы владельцем: 40% с услуг, 10% с проданной
косметики, гарант 4 000 за смену у всех троих. По отчёту они не выводятся и
с ним не сходятся: в августе выплаты барберам составили 20% от услуг, в
сентябре 64%. Отчёт кассовый, выплаты смещены на месяц вперёд, поэтому
источником взяты слова владельца, а не эти доли.

Revision ID: 0002_cost_model
Revises: 0001_initial
"""

import sqlalchemy as sa

from alembic import op

revision = "0002_cost_model"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def _has_column(table: str, column: str) -> bool:
    return column in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    # Первая миграция создаёт схему прямо из моделей, то есть на чистой базе
    # эта таблица уже появится вместе с ней. На базе, заведённой раньше, —
    # нет. Поэтому обе ветки проверяются, а не предполагаются: без этого
    # установка с нуля падала на «таблица уже существует».
    if _has_table("cost_model"):
        _seed_defaults()
        _rename_plan_column()
        return

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
        # Бизнес- и прочие расходы из отчёта, среднее за два месяца:
        # (11 980 + 49 060) / 2 + (17 137 + 12 121) / 2 = 45 149.
        # Разброс большой, но исключать их совсем — занижать расходы.
        "other_fixed_monthly": "45149.00",
        "admin_per_shift": "4000.00",       # сменный администратор, за смену
        "admin_shifts_per_month": "15.50",  # 15-16 смен, остальные — за управляющим
        "materials_pct": "3.50",           # расходники: 29 060 от 824 465 = 3,52%
        "acquiring_pct": "0.00",           # в отчёте нуль
        "master_commission_pct": "40.00",   # с услуг, подтверждено владельцем
        "product_commission_pct": "10.00",  # с косметики, подтверждено владельцем
    }])


    _rename_plan_column()


def _seed_defaults() -> None:
    """Заполнить настройки, если строки ещё нет.

    Таблица могла появиться вместе со схемой, но пустой. Нули в ней опаснее
    отсутствия: порог безубыточности обнулится, и любой день покажется
    прибыльным.
    """
    bind = op.get_bind()
    existing = bind.execute(sa.text("SELECT COUNT(*) FROM cost_model")).scalar()
    if existing:
        return

    # На чистой базе таблицу создаёт первая миграция прямо из моделей, а там
    # постоянные расходы давно свёрнуты в одно поле (см. 0003). Заполнять по
    # разбору статей в этом случае нечего — колонок таких нет.
    if _has_column("cost_model", "fixed_monthly"):
        bind.execute(sa.text(
            "INSERT INTO cost_model ("
            "id, fixed_monthly, materials_pct, acquiring_pct,"
            " master_commission_pct, product_commission_pct) VALUES ("
            "1, 372117, 3.5, 0, 40, 10)"
        ))
        return

    bind.execute(sa.text(
        "INSERT INTO cost_model ("
        "id, rent_monthly, utilities_monthly, manager_monthly, cleaning_monthly,"
        " taxes_monthly, other_fixed_monthly, admin_per_shift,"
        " admin_shifts_per_month, materials_pct, acquiring_pct,"
        " master_commission_pct, product_commission_pct) VALUES ("
        "1, 170000, 15000, 90000, 15000, 6000, 45149, 4000, 15.5, 3.5, 0, 40, 10)"
    ))


def _rename_plan_column() -> None:
    """План на месяц задаётся по прибыли, а не по выручке.

    На чистой базе колонка уже называется правильно — она создана из моделей.
    Переименовывать её второй раз нельзя, поэтому имя проверяется.
    """
    if _has_column("plan_targets", "revenue_target"):
        op.alter_column("plan_targets", "revenue_target", new_column_name="profit_target")


def downgrade() -> None:
    if _has_column("plan_targets", "profit_target"):
        op.alter_column("plan_targets", "profit_target", new_column_name="revenue_target")
    if _has_table("cost_model"):
        op.drop_table("cost_model")
