"""Журнал выгрузок: когда данные обновлялись в последний раз.

Время последней выгрузки жило только в памяти процесса. После каждого
перезапуска Директора оно обнулялось, и показать на экране «обновлено тогда-то»
было нечем: при свежих данных стояло бы «никогда».

Строка на каждую выгрузку, а не одна перезаписываемая. Владельцу важно
отличать «последняя удачная была час назад» от «последние пять попыток
упали»: во втором случае цифры на экране устарели, и это надо видеть.

Revision ID: 0004_sync_runs
Revises: 0003_fixed_monthly
"""

import sqlalchemy as sa

from alembic import op

revision = "0004_sync_runs"
down_revision = "0003_fixed_monthly"
branch_labels = None
depends_on = None

ТАБЛИЦА = "sync_runs"


def _существует(имя: str) -> bool:
    инспектор = sa.inspect(op.get_bind())
    return имя in инспектор.get_table_names()


def upgrade() -> None:
    # Проверка на существование — чтобы повторный запуск не падал. Миграции
    # на установке владельца запускаются при каждом старте Директора.
    if _существует(ТАБЛИЦА):
        return

    op.create_table(
        ТАБЛИЦА,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error", sa.String(length=500), nullable=True),
        sa.Column("staff_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("services_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("clients_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("visits_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sales_count", sa.Integer(), nullable=False, server_default="0"),
    )
    # По этим двум полям идёт единственный запрос: последняя удачная выгрузка
    # и последняя попытка.
    op.create_index("ix_sync_runs_started_at", ТАБЛИЦА, ["started_at"])
    op.create_index("ix_sync_runs_ok", ТАБЛИЦА, ["ok"])


def downgrade() -> None:
    if not _существует(ТАБЛИЦА):
        return
    op.drop_index("ix_sync_runs_ok", table_name=ТАБЛИЦА)
    op.drop_index("ix_sync_runs_started_at", table_name=ТАБЛИЦА)
    op.drop_table(ТАБЛИЦА)
