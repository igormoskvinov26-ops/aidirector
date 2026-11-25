"""yclients_id — расширить до BigInteger у employees/clients/services/products/visits.

Revision ID: 0017_yclients_id_bigint
Revises: 0016_status_loyalty_variants

YCLIENTS нумерует записи одним общим счётчиком на все салоны платформы, и он
перевалил за потолок 32-битного INTEGER (2 147 483 647): с 14.11.2026 выгрузка
визитов салона падала на номере записи 2168275835 («integer out of range» /
«value out of int32 range»). У sales колонка уже BigInteger; здесь доводим
остальные таблицы, где лежит номер из того же счётчика.

Миграция идемпотентна: на базе, где колонки уже расширены (так сделала
сборка 9.17.13, если её успели запустить), ничего не меняет.
"""

import sqlalchemy as sa

from alembic import op

revision = "0017_yclients_id_bigint"
down_revision = "0016_status_loyalty_variants"
branch_labels = None
depends_on = None

ТАБЛИЦЫ = ("employees", "clients", "services", "products", "visits")


def _тип(таблица: str) -> str:
    for колонка in sa.inspect(op.get_bind()).get_columns(таблица):
        if колонка["name"] == "yclients_id":
            return str(колонка["type"]).upper()
    return ""


def upgrade() -> None:
    for таблица in ТАБЛИЦЫ:
        тип = _тип(таблица)
        if тип and "BIG" not in тип:
            op.alter_column(таблица, "yclients_id", type_=sa.BigInteger(), existing_nullable=False)


def downgrade() -> None:
    for таблица in ТАБЛИЦЫ:
        if "BIG" in _тип(таблица):
            op.alter_column(таблица, "yclients_id", type_=sa.Integer(), existing_nullable=False)
