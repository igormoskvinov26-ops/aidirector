"""Управляемые настройки интеграций и журнал их изменений.

Раньше ключи YCLIENTS можно было задать только в .env на сервере: владелец
без доступа к серверу не мог ни сменить токен, ни понять, почему перестало
обновляться. Теперь они настраиваются в разделе «Настройки → Интеграции»,
а .env остаётся запасным вариантом для уже развёрнутых установок.

Revision ID: 0009_app_settings
Revises: 0008_telegram_settings
"""

import sqlalchemy as sa

from alembic import op

revision = "0009_app_settings"
down_revision = "0008_telegram_settings"
branch_labels = None
depends_on = None

НАСТРОЙКИ = "app_settings"
ЖУРНАЛ = "settings_audit"


def _существует(имя: str) -> bool:
    инспектор = sa.inspect(op.get_bind())
    return имя in инспектор.get_table_names()


def upgrade() -> None:
    if not _существует(НАСТРОЙКИ):
        op.create_table(
            НАСТРОЙКИ,
            sa.Column("key", sa.String(64), primary_key=True),
            sa.Column("value", sa.Text(), nullable=False),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("updated_by", sa.String(64), nullable=True),
        )

    if not _существует(ЖУРНАЛ):
        op.create_table(
            ЖУРНАЛ,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("who", sa.String(64), nullable=False),
            sa.Column("integration", sa.String(32), nullable=False),
            sa.Column("key", sa.String(64), nullable=False),
            sa.Column("action", sa.String(16), nullable=False),
        )
        op.create_index(f"ix_{ЖУРНАЛ}_at", ЖУРНАЛ, ["at"])


def downgrade() -> None:
    if _существует(ЖУРНАЛ):
        op.drop_index(f"ix_{ЖУРНАЛ}_at", table_name=ЖУРНАЛ)
        op.drop_table(ЖУРНАЛ)
    if _существует(НАСТРОЙКИ):
        op.drop_table(НАСТРОЙКИ)
