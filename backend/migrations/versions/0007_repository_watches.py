"""Track GitHub repository scans per account."""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"


def upgrade():
    op.create_table(
        "repository_watches",
        sa.Column("account_id", sa.String(32), sa.ForeignKey("accounts.id"), primary_key=True),
        sa.Column("repository_id", sa.String(32), primary_key=True),
        sa.Column("github_id", sa.String(32), nullable=False),
        sa.Column("full_name", sa.String(), nullable=False),
        sa.Column("branch", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("due", sa.Float(), nullable=False),
        sa.Column("sha", sa.String(40)),
        sa.Column("run_id", sa.String(32), sa.ForeignKey("runs.id", ondelete="SET NULL")),
        sa.Column("baseline_id", sa.String(32), sa.ForeignKey("runs.id", ondelete="SET NULL")),
        sa.Column("error", sa.String()),
    )


def downgrade():
    op.drop_table("repository_watches")
