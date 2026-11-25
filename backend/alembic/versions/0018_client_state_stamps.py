"""clients.state_stamps — метки свежести полей состояния обзвона клиента.

Revision ID: 0018_client_state_stamps
Revises: 0017_yclients_id_bigint

Салон и Мак обмениваются состоянием клиентов (статус звонка, дата перезвона,
светофор, «не звонить», теги) через общий сервер. Без меток свежести чужая
копия затирала только что поставленную отметку целиком (разбор жалобы
22.11.2026). Идемпотентна.
"""

import sqlalchemy as sa

from alembic import op

revision = "0018_client_state_stamps"
down_revision = "0017_yclients_id_bigint"
branch_labels = None
depends_on = None


def _есть() -> bool:
    return "state_stamps" in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("clients")}


def upgrade() -> None:
    if not _есть():
        op.add_column("clients", sa.Column("state_stamps", sa.JSON(), nullable=True))


def downgrade() -> None:
    if _есть():
        op.drop_column("clients", "state_stamps")
