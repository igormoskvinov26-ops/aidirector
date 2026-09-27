"""Токен бота и чат для рассылки — одна строка, настраивается в интерфейсе.

Решение владельца 27.09.2026: раньше TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID
можно было задать только через .env на сервере. Теперь это делается на
странице «Смена»; .env остаётся запасным вариантом для уже развёрнутых
установок.

Revision ID: 0008_telegram_settings
Revises: 0007_cash_balances
"""

import sqlalchemy as sa

from alembic import op

revision = "0008_telegram_settings"
down_revision = "0007_cash_balances"
branch_labels = None
depends_on = None

ТАБЛИЦА = "telegram_settings"


def _существует(имя: str) -> bool:
    инспектор = sa.inspect(op.get_bind())
    return имя in инспектор.get_table_names()


def upgrade() -> None:
    if _существует(ТАБЛИЦА):
        return
    op.create_table(
        ТАБЛИЦА,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("bot_token", sa.Text(), nullable=False),
        sa.Column("chat_id", sa.String(64), nullable=False),
        sa.Column("bot_username", sa.String(255), nullable=True),
        sa.Column("chat_title", sa.String(255), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    if not _существует(ТАБЛИЦА):
        return
    op.drop_table(ТАБЛИЦА)
