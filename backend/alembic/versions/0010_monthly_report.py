"""Месячный отчёт: проверка звонков по YCLIENTS, настройки и snapshot месяца.

Revision ID: 0010_monthly_report
Revises: 0009_app_settings
"""

import sqlalchemy as sa

from alembic import op

revision = "0010_monthly_report"
down_revision = "0009_app_settings"
branch_labels = None
depends_on = None

ПОПЫТКИ = "contact_attempts"
НОВЫЕ_КОЛОНКИ = (
    ("admin_staff_id", sa.Integer()),
    ("verification_status", sa.String(20)),
    ("yclients_record_id", sa.BigInteger()),
    ("verified_at", sa.DateTime(timezone=True)),
    ("verification_checked_at", sa.DateTime(timezone=True)),
    ("verification_note", sa.Text()),
)


def _таблицы() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _колонки(таблица: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(таблица)}


def upgrade() -> None:
    есть = _колонки(ПОПЫТКИ)
    for имя, тип in НОВЫЕ_КОЛОНКИ:
        if имя not in есть:
            op.add_column(ПОПЫТКИ, sa.Column(имя, тип, nullable=True))

    # Прежние нажатия «Записан» нужно проверить задним числом: статус pending,
    # а не «подтверждено» и не «не подтверждено».
    op.execute(
        sa.text(
            f"UPDATE {ПОПЫТКИ} SET verification_status = 'pending' "
            "WHERE outcome = 'booked' AND verification_status IS NULL"
        )
    )

    индексы = {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(ПОПЫТКИ)}
    for имя in ("admin_staff_id", "verification_status", "yclients_record_id"):
        if f"ix_{ПОПЫТКИ}_{имя}" not in индексы:
            op.create_index(f"ix_{ПОПЫТКИ}_{имя}", ПОПЫТКИ, [имя])

    таблицы = _таблицы()
    if "report_settings" not in таблицы:
        op.create_table(
            "report_settings",
            sa.Column("key", sa.String(64), primary_key=True),
            sa.Column("value", sa.JSON(), nullable=True),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True),
                server_default=sa.func.now(), nullable=False,
            ),
        )
    if "monthly_report_snapshots" not in таблицы:
        op.create_table(
            "monthly_report_snapshots",
            sa.Column("report_month", sa.String(7), primary_key=True),
            sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("master_metrics", sa.JSON(), nullable=False),
            sa.Column("admin_metrics", sa.JSON(), nullable=False),
            sa.Column("targets", sa.JSON(), nullable=False),
            sa.Column("data_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("warnings", sa.JSON(), nullable=False),
        )


def downgrade() -> None:
    op.drop_table("monthly_report_snapshots")
    op.drop_table("report_settings")
    for имя in ("yclients_record_id", "verification_status", "admin_staff_id"):
        op.drop_index(f"ix_{ПОПЫТКИ}_{имя}", table_name=ПОПЫТКИ)
    for имя, _ in reversed(НОВЫЕ_КОЛОНКИ):
        op.drop_column(ПОПЫТКИ, имя)
