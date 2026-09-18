"""Комментарий администратора к клиенту.

Отдельная колонка, а не привязка к попытке звонка (contact_attempts):
задачи обзвона (contact_tasks) пересобираются заново каждый день —
refresh_tasks() удаляет все открытые и создаёт новые. Комментарий вида
«перезвонить завтра», написанный сегодня, должен пережить эту пересборку
и снова оказаться на карточке того же клиента, когда для него завтра
создастся новая задача. Единственное место, которое переживает
пересборку, — сам клиент.

Revision ID: 0005_client_admin_note
Revises: 0004_sync_runs
"""

import sqlalchemy as sa

from alembic import op

revision = "0005_client_admin_note"
down_revision = "0004_sync_runs"
branch_labels = None
depends_on = None

ТАБЛИЦА = "clients"
КОЛОНКА = "admin_note"


def _есть_колонка() -> bool:
    инспектор = sa.inspect(op.get_bind())
    имена = {c["name"] for c in инспектор.get_columns(ТАБЛИЦА)}
    return КОЛОНКА in имена


def upgrade() -> None:
    if _есть_колонка():
        return
    op.add_column(ТАБЛИЦА, sa.Column(КОЛОНКА, sa.Text(), nullable=True))


def downgrade() -> None:
    if not _есть_колонка():
        return
    op.drop_column(ТАБЛИЦА, КОЛОНКА)
