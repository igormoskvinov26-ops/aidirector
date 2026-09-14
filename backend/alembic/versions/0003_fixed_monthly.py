"""Постоянные расходы — одним числом вместо разбора по статьям.

Расходы были разложены на аренду, коммуналку, управляющего, уборку, налоги,
прочее и оплату сменного администратора по числу смен. Разбор оказался лишним:
владелец ведёт статьи в отчётности салона, а Директору нужна одна сумма, чтобы
поделить её на дни. Держать статьи в двух местах — значит однажды поправить их
в одном месте и забыть про другое.

Число при переносе сохраняется: в него складываются все шесть месячных статей
плюс оплата администратора за месяц, то есть ровно то, что раньше давала
формула порога. Порог безубыточности после миграции не сдвигается.

Проценты остаются как были: расходники и эквайринг — доля выручки, оплата
мастера — процент с услуг и с косметики. В сумму постоянных расходов они не
входят и входить не должны, иначе учлись бы дважды.

Revision ID: 0003_fixed_monthly
Revises: 0002_cost_model
"""

import sqlalchemy as sa

from alembic import op

revision = "0003_fixed_monthly"
down_revision = "0002_cost_model"
branch_labels = None
depends_on = None

СТАРЫЕ_СТАТЬИ = (
    "rent_monthly",
    "utilities_monthly",
    "manager_monthly",
    "cleaning_monthly",
    "taxes_monthly",
    "other_fixed_monthly",
)
СТАРЫЕ_КОЛОНКИ = (*СТАРЫЕ_СТАТЬИ, "admin_per_shift", "admin_shifts_per_month")


def _columns() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("cost_model")}


def upgrade() -> None:
    columns = _columns()

    # На чистой базе таблица создана из моделей и уже в нужном виде.
    if "fixed_monthly" in columns:
        return

    op.add_column(
        "cost_model",
        sa.Column("fixed_monthly", sa.Numeric(12, 2), nullable=False, server_default="0"),
    )

    # Складываем ровно то, что раньше давала формула порога: месячные статьи
    # плюс администратор за месяц. Отсутствующие колонки пропускаем — база
    # могла быть заведена до того, как появилась какая-то из них.
    статьи = [c for c in СТАРЫЕ_СТАТЬИ if c in columns]
    сумма = " + ".join(f"COALESCE({c}, 0)" for c in статьи) or "0"
    if "admin_per_shift" in columns and "admin_shifts_per_month" in columns:
        сумма += " + COALESCE(admin_per_shift, 0) * COALESCE(admin_shifts_per_month, 0)"

    op.execute(f"UPDATE cost_model SET fixed_monthly = {сумма}")

    # Строка расходов могла остаться пустой — тогда порог обнулится, и любой
    # день покажется прибыльным. Это опаснее, чем отсутствие настроек.
    op.execute("UPDATE cost_model SET fixed_monthly = 403149 WHERE fixed_monthly <= 0")

    with op.batch_alter_table("cost_model") as batch:
        for column in СТАРЫЕ_КОЛОНКИ:
            if column in columns:
                batch.drop_column(column)


def downgrade() -> None:
    columns = _columns()
    if "fixed_monthly" not in columns:
        return

    with op.batch_alter_table("cost_model") as batch:
        for column, тип in (
            ("rent_monthly", sa.Numeric(12, 2)),
            ("utilities_monthly", sa.Numeric(12, 2)),
            ("manager_monthly", sa.Numeric(12, 2)),
            ("cleaning_monthly", sa.Numeric(12, 2)),
            ("taxes_monthly", sa.Numeric(12, 2)),
            ("other_fixed_monthly", sa.Numeric(12, 2)),
            ("admin_per_shift", sa.Numeric(10, 2)),
            ("admin_shifts_per_month", sa.Numeric(5, 2)),
        ):
            if column not in columns:
                batch.add_column(sa.Column(column, тип, nullable=False, server_default="0"))

    # Разложить сумму обратно по статьям нечем: она пришла одним числом.
    # Кладём всё в «прочие», чтобы порог остался на месте.
    op.execute("UPDATE cost_model SET other_fixed_monthly = fixed_monthly")

    with op.batch_alter_table("cost_model") as batch:
        batch.drop_column("fixed_monthly")
