"""Смены: утренний план, вечерний факт и время прихода-ухода мастеров.

Модуль «Открытие / закрытие смены» по ТЗ владельца от 23.09.2026. Смена
хранится разобранной по показателям, а не готовым текстом сообщения: по
тексту нельзя построить ни одного отчёта, а вопрос «как менялся план по
дням» задаётся первым.

На дату — ровно одна смена: повторное нажатие «Открыть смену» показывает
уже открытую, а не заводит вторую.

Revision ID: 0006_shifts
Revises: 0005_client_admin_note
"""

import sqlalchemy as sa

from alembic import op

revision = "0006_shifts"
down_revision = "0005_client_admin_note"
branch_labels = None
depends_on = None

СМЕНЫ = "shifts"
МАСТЕРА = "shift_employees"


def _существует(имя: str) -> bool:
    инспектор = sa.inspect(op.get_bind())
    return имя in инспектор.get_table_names()


def upgrade() -> None:
    # Проверка на существование — миграции на установке владельца запускаются
    # при каждом старте Директора, повторный запуск падать не должен.
    if not _существует(СМЕНЫ):
        op.create_table(
            СМЕНЫ,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("shift_date", sa.Date(), nullable=False),
            sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("opening_snapshot", sa.JSON(), nullable=True),
            sa.Column("closing_snapshot", sa.JSON(), nullable=True),
            sa.Column("opening_telegram_sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("opening_telegram_message_id", sa.BigInteger(), nullable=True),
            sa.Column("closing_telegram_sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("closing_telegram_message_id", sa.BigInteger(), nullable=True),
        )
        op.create_index("ix_shifts_shift_date", СМЕНЫ, ["shift_date"], unique=True)

    if not _существует(МАСТЕРА):
        op.create_table(
            МАСТЕРА,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("shift_id", sa.Integer(), sa.ForeignKey("shifts.id"), nullable=False),
            sa.Column("staff_id", sa.Integer(), nullable=False),
            sa.Column("staff_name_snapshot", sa.String(length=255), nullable=False),
            # Время в HH:MM строкой: его вводит человек, и хранить его надо
            # ровно так, как он ввёл. Точка во времени тут ни при чём —
            # это отметка на часах, а не момент в календаре.
            sa.Column("arrival_time", sa.String(length=5), nullable=True),
            sa.Column("departure_time", sa.String(length=5), nullable=True),
            sa.UniqueConstraint("shift_id", "staff_id", name="uq_shift_employee"),
        )
        op.create_index("ix_shift_employees_shift_id", МАСТЕРА, ["shift_id"])
        op.create_index("ix_shift_employees_staff_id", МАСТЕРА, ["staff_id"])


def downgrade() -> None:
    if _существует(МАСТЕРА):
        op.drop_index("ix_shift_employees_staff_id", table_name=МАСТЕРА)
        op.drop_index("ix_shift_employees_shift_id", table_name=МАСТЕРА)
        op.drop_table(МАСТЕРА)
    if _существует(СМЕНЫ):
        op.drop_index("ix_shifts_shift_date", table_name=СМЕНЫ)
        op.drop_table(СМЕНЫ)
