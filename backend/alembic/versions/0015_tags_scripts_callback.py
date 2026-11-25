"""Теги клиентов, редактируемые скрипты и плановая дата следующего контакта.

Revision ID: 0015_tags_scripts_callback
Revises: 0014_call_tracking

Три задачи владельца от 16.10.2026 в одной миграции:

* ``clients.next_contact_*`` — админ планирует, когда вернуться к клиенту.
  Поле на клиенте, а не на задаче: задачи обзвона пересобираются каждый день.
* ``client_tags`` / ``client_tag_links`` — свои категории («переехал»,
  «записывает супруга», «акция»). Флаг ``exclude_from_calls`` убирает клиента
  из обычной очереди, в отличие от «НЕ ЗВОНИТЬ!» снимается одним кликом.
* ``scripts`` — тексты звонка и сообщения под группу или тег, правятся из
  интерфейса. До этого скрипты были зашиты в код.
"""

import sqlalchemy as sa

from alembic import op

revision = "0015_tags_scripts_callback"
down_revision = "0014_call_tracking"
branch_labels = None
depends_on = None

КОЛОНКИ = (
    ("clients", "next_contact_at", sa.Date(), {"nullable": True}),
    ("clients", "next_contact_note", sa.String(200), {"nullable": True}),
    ("clients", "next_contact_by", sa.String(64), {"nullable": True}),
)


def _колонки(таблица: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(таблица)}


def _таблицы() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    for таблица, имя, тип, опции in КОЛОНКИ:
        if имя not in _колонки(таблица):
            op.add_column(таблица, sa.Column(имя, тип, **опции))

    есть = _таблицы()
    if "client_tags" not in есть:
        op.create_table(
            "client_tags",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("code", sa.String(40), nullable=False, unique=True),
            sa.Column("name", sa.String(80), nullable=False),
            sa.Column("color", sa.String(16), nullable=True),
            sa.Column("exclude_from_calls", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("promo", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    if "client_tag_links" not in есть:
        op.create_table(
            "client_tag_links",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False, index=True),
            sa.Column("tag_id", sa.Integer(), sa.ForeignKey("client_tags.id"), nullable=False, index=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("created_by", sa.String(64), nullable=True),
            sa.UniqueConstraint("client_id", "tag_id", name="uq_client_tag"),
        )
    if "scripts" not in есть:
        op.create_table(
            "scripts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("kind", sa.String(10), nullable=False),  # group | tag
            sa.Column("key", sa.String(40), nullable=False),
            sa.Column("phone_text", sa.Text(), nullable=True),
            sa.Column("message_text", sa.Text(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_by", sa.String(64), nullable=True),
            sa.UniqueConstraint("kind", "key", name="uq_script_kind_key"),
        )


def downgrade() -> None:
    есть = _таблицы()
    for имя in ("scripts", "client_tag_links", "client_tags"):
        if имя in есть:
            op.drop_table(имя)
    for таблица, имя, _, _ in КОЛОНКИ:
        if имя in _колонки(таблица):
            op.drop_column(таблица, имя)
