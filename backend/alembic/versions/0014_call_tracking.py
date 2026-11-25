"""Дата последнего звонка у клиента и отметка «был потерян» у попытки.

Revision ID: 0014_call_tracking
Revises: 0013_acquiring_source

Обзвон перестал прятать обработанных клиентов: они остаются в списке и
уходят вниз по дате последнего звонка, а строка подкрашивается по исходу.
Для этого дату надо помнить на клиенте — задачи обзвона пересобираются
каждый день заново, и на них она бы не пережила ночь.

``was_lost`` на попытке — был ли клиент потерянным в момент звонка. Нужен
для вкладки «Возвращённые»: сегмент клиента после записи меняется, и
задним числом «кого мы вернули» уже не посчитать.
"""

import sqlalchemy as sa

from alembic import op

revision = "0014_call_tracking"
down_revision = "0013_acquiring_source"
branch_labels = None
depends_on = None

КОЛОНКИ = (
    ("clients", "last_call_at", sa.DateTime(timezone=True), {"nullable": True}),
    ("clients", "last_call_outcome", sa.String(20), {"nullable": True}),
    ("contact_attempts", "was_lost", sa.Boolean(), {"nullable": False, "server_default": sa.false()}),
)


def _колонки(таблица: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(таблица)}


def upgrade() -> None:
    for таблица, имя, тип, опции in КОЛОНКИ:
        if имя not in _колонки(таблица):
            op.add_column(таблица, sa.Column(имя, тип, **опции))


def downgrade() -> None:
    for таблица, имя, _, _ in КОЛОНКИ:
        if имя in _колонки(таблица):
            op.drop_column(таблица, имя)
