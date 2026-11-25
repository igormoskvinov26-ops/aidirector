"""Статус контакта, светофор лояльности, кто звонил и варианты скриптов.

Revision ID: 0016_status_loyalty_variants
Revises: 0015_tags_scripts_callback

Пакет задач владельца от 16.10.2026:

* ``clients.call_status`` — статус последнего общения («записан», «перезвонить»,
  «не дозвонились», «не звонить», «без записи»). Раньше исход жил только в
  попытке звонка, и в базе его не было видно.
* ``clients.last_call_by`` — кто звонил. Нужен, чтобы понимать, чей комментарий.
* ``clients.loyalty`` — светофор: зелёный, жёлтый, красный. Ставит админ по
  тону разговора, горит в карточке постоянно.
* Скрипт перестаёт быть одним текстом: у группы и у тега несколько вариантов
  (начало разговора, ветки по причине ухода, завершение, сообщение). Поэтому в
  ``scripts`` добавляются ``variant``, ``title``, ``hint``, ``sort``, а
  уникальность переезжает с (kind, key) на (kind, key, variant).
"""

import sqlalchemy as sa

from alembic import op

revision = "0016_status_loyalty_variants"
down_revision = "0015_tags_scripts_callback"
branch_labels = None
depends_on = None

КОЛОНКИ = (
    ("clients", "call_status", sa.String(20), {"nullable": True}),
    ("clients", "last_call_by", sa.String(64), {"nullable": True}),
    ("clients", "loyalty", sa.String(8), {"nullable": True}),
    ("clients", "loyalty_at", sa.DateTime(timezone=True), {"nullable": True}),
    ("clients", "loyalty_by", sa.String(64), {"nullable": True}),
    ("scripts", "variant", sa.String(40), {"nullable": False, "server_default": "main"}),
    ("scripts", "title", sa.String(80), {"nullable": True}),
    ("scripts", "hint", sa.Text(), {"nullable": True}),
    ("scripts", "sort", sa.Integer(), {"nullable": False, "server_default": "0"}),
)


def _колонки(таблица: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(таблица)}


def _ограничения(таблица: str) -> set[str]:
    i = sa.inspect(op.get_bind())
    return {c["name"] for c in i.get_unique_constraints(таблица) if c.get("name")}


def upgrade() -> None:
    for таблица, имя, тип, опции in КОЛОНКИ:
        if имя not in _колонки(таблица):
            op.add_column(таблица, sa.Column(имя, тип, **опции))
    # SQLite уникальные ограничения так не переписывает, но там схема всегда
    # создаётся из моделей заново — чинить нужно только боевой Postgres.
    if op.get_bind().dialect.name != "sqlite":
        есть = _ограничения("scripts")
        if "uq_script_kind_key" in есть:
            op.drop_constraint("uq_script_kind_key", "scripts", type_="unique")
        if "uq_script_kind_key_variant" not in есть:
            op.create_unique_constraint(
                "uq_script_kind_key_variant", "scripts", ["kind", "key", "variant"]
            )


def downgrade() -> None:
    if op.get_bind().dialect.name != "sqlite" and "uq_script_kind_key_variant" in _ограничения("scripts"):
        op.drop_constraint("uq_script_kind_key_variant", "scripts", type_="unique")
    for таблица, имя, _, _ in КОЛОНКИ:
        if имя in _колонки(таблица):
            op.drop_column(таблица, имя)
