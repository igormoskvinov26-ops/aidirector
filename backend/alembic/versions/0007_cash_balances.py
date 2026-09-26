"""Остатки в кассе и на расчётном счёте — одна строка, обновляемая владельцем.

Решение владельца 26.09.2026, часть блока «Деньги» в закрытии смены. Регистр
день-за-днём YCLIENTS вести не позволяет без подтверждённых полей нал/безнал
и признака расхода — до их подтверждения остаток хранится как известное
значение на дату as_of. Долг перед другим счётом YCLIENTS не видит вовсе —
это исключительно ручная цифра.

Revision ID: 0007_cash_balances
Revises: 0006_shifts
"""

import sqlalchemy as sa

from alembic import op

revision = "0007_cash_balances"
down_revision = "0006_shifts"
branch_labels = None
depends_on = None

ТАБЛИЦА = "cash_balances"


def _существует(имя: str) -> bool:
    инспектор = sa.inspect(op.get_bind())
    return имя in инспектор.get_table_names()


def upgrade() -> None:
    if _существует(ТАБЛИЦА):
        return
    op.create_table(
        ТАБЛИЦА,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cash_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("cash_as_of", sa.Date(), nullable=False),
        sa.Column("settlement_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("settlement_as_of", sa.Date(), nullable=False),
        sa.Column("other_account_debt", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("other_debt_note", sa.Text(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    if not _существует(ТАБЛИЦА):
        return
    op.drop_table(ТАБЛИЦА)
