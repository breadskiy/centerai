"""Persist detection summaries with completion events."""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"


def upgrade():
    op.add_column("events", sa.Column("stage", sa.JSON()))


def downgrade():
    op.drop_column("events", "stage")
