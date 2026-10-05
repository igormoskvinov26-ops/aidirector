"""Отчёты банка по эквайрингу для сверки с кассой YCLIENTS.

Revision ID: 0011_acquiring_rows
Revises: 0010_monthly_report
"""

import sqlalchemy as sa

from alembic import op

revision = "0011_acquiring_rows"
down_revision = "0010_monthly_report"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "acquiring_rows" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "acquiring_rows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("op_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("fee", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("net", sa.Numeric(14, 2), nullable=False),
        sa.Column("source_file", sa.String(255), nullable=False),
        sa.Column(
            "uploaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_acquiring_rows_op_date", "acquiring_rows", ["op_date"])


def downgrade() -> None:
    if "acquiring_rows" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_index("ix_acquiring_rows_op_date", table_name="acquiring_rows")
        op.drop_table("acquiring_rows")
