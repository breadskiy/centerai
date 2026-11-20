"""Persist scenario descriptions in the editor and its version history."""

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"


def upgrade():
    for table in ("workflows", "workflow_versions"):
        op.add_column(
            table,
            sa.Column("description", sa.String(), nullable=False, server_default=""),
        )


def downgrade():
    for table in ("workflow_versions", "workflows"):
        op.drop_column(table, "description")
