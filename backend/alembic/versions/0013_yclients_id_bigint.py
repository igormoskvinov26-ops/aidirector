"""yclients_id — расширить до BigInteger у employees/clients/services/products/visits.

Revision ID: 0013_yclients_id_bigint
Revises: 0012_client_do_not_call

YCLIENTS нумерует записи одним общим счётчиком на все салоны платформы:
он годами растёт и у части салонов уже перевалил за потолок 32-битного
INTEGER (2 147 483 647) — конкретно это обнаружилось на номере визита
(значение из рабочей ошибки: 2150703160), из-за чего синхронизация визитов
стала падать. Тот же счётчик стоит и за клиентами/сотрудниками/услугами/
товарами — у Sale это уже было расширено раньше, здесь доводим до конца
оставшиеся таблицы, чтобы не чинить ту же проблему по одной таблице за раз.
"""

import sqlalchemy as sa

from alembic import op

revision = "0013_yclients_id_bigint"
down_revision = "0012_client_do_not_call"
branch_labels = None
depends_on = None

ТАБЛИЦЫ = ("employees", "clients", "services", "products", "visits")


def _тип(таблица: str) -> str:
    [колонка] = [c for c in sa.inspect(op.get_bind()).get_columns(таблица) if c["name"] == "yclients_id"]
    return str(колонка["type"]).upper()


def upgrade() -> None:
    for таблица in ТАБЛИЦЫ:
        if "BIG" not in _тип(таблица):
            op.alter_column(таблица, "yclients_id", type_=sa.BigInteger(), existing_nullable=False)


def downgrade() -> None:
    for таблица in ТАБЛИЦЫ:
        if "BIG" in _тип(таблица):
            op.alter_column(таблица, "yclients_id", type_=sa.Integer(), existing_nullable=False)
