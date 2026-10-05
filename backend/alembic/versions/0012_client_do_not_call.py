"""Признак «НЕ ЗВОНИТЬ!» у клиента: кто и когда пометил.

Revision ID: 0012_client_do_not_call
Revises: 0011_acquiring_rows

Помеченный клиент больше не попадает в обзвон. Своё поле, не из YCLIENTS:
выгрузка его не трогает (решение владельца 04.10.2026).
"""

import sqlalchemy as sa

from alembic import op

revision = "0012_client_do_not_call"
down_revision = "0011_acquiring_rows"
branch_labels = None
depends_on = None

КОЛОНКИ = (
    ("do_not_call", sa.Boolean(), {"nullable": False, "server_default": sa.false()}),
    ("do_not_call_at", sa.DateTime(timezone=True), {"nullable": True}),
    ("do_not_call_by", sa.String(64), {"nullable": True}),
)


def _есть() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("clients")}


def upgrade() -> None:
    есть = _есть()
    for имя, тип, опции in КОЛОНКИ:
        if имя not in есть:
            op.add_column("clients", sa.Column(имя, тип, **опции))


def downgrade() -> None:
    есть = _есть()
    for имя, _, _ in КОЛОНКИ:
        if имя in есть:
            op.drop_column("clients", имя)
