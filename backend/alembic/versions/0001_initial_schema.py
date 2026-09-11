"""Initial schema.

Generated from app.models.models. Before this, the schema was created by
``Base.metadata.create_all`` at startup, which meant the first model change had
to be applied to the production database by hand.

Revision ID: 0001_initial
Revises:
"""

from alembic import op

import app.models.models as models  # noqa: F401  (registers metadata)
from app.database import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
