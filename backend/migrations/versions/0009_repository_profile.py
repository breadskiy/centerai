"""Give each GitHub watch a scan profile and remember the last one run."""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"


def upgrade():
    op.add_column("repository_watches", sa.Column("profile", sa.String(120), nullable=False, server_default="full"))
    op.add_column("repository_watches", sa.Column("scan_profile", sa.String(120), nullable=False, server_default="full"))


def downgrade():
    op.drop_column("repository_watches", "scan_profile")
    op.drop_column("repository_watches", "profile")
