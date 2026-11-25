"""Поток отчёта у строки эквайринга: один день — несколько файлов.

Revision ID: 0013_acquiring_source
Revises: 0012_client_do_not_call

Банк присылает отдельно отчёт по картам и отдельно по СБП. Раньше повторная
загрузка за те же даты стирала всё, что уже было за эти дни, — второй файл
затирал первый. Теперь строка помнит, из какого потока отчётов она пришла,
и заменяются только строки того же потока.

Строкам, загруженным до этого обновления, поток не присваивается: пустое
значение означает «старый отчёт без потока», и первая же новая загрузка за
те же даты их заменит. Иначе прежние и новые строки сложились бы и день
посчитался бы дважды.
"""

import sqlalchemy as sa

from alembic import op

revision = "0013_acquiring_source"
down_revision = "0012_client_do_not_call"
branch_labels = None
depends_on = None

КОЛОНКА = "source"


def _есть() -> bool:
    return КОЛОНКА in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("acquiring_rows")}


def upgrade() -> None:
    if not _есть():
        op.add_column(
            "acquiring_rows",
            sa.Column(КОЛОНКА, sa.String(40), nullable=False, server_default=""),
        )


def downgrade() -> None:
    if _есть():
        op.drop_column("acquiring_rows", КОЛОНКА)
