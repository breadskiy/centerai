"""Store the commit date separately from the latest queued scan."""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"


def upgrade():
    op.add_column("repository_watches", sa.Column("head_sha", sa.String(40)))
    op.add_column("repository_watches", sa.Column("head_committed_at", sa.Float()))


def downgrade():
    op.drop_column("repository_watches", "head_committed_at")
    op.drop_column("repository_watches", "head_sha")
