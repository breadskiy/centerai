"""Save each repository's visual scenario and the revision used by its run."""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"


def upgrade():
    op.add_column("repository_watches", sa.Column("scenario", sa.JSON()))
    op.add_column(
        "repository_watches",
        sa.Column(
            "scenario_revision", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "repository_watches",
        sa.Column(
            "scan_scenario_revision", sa.Integer(), nullable=False, server_default="0"
        ),
    )


def downgrade():
    op.drop_column("repository_watches", "scan_scenario_revision")
    op.drop_column("repository_watches", "scenario_revision")
    op.drop_column("repository_watches", "scenario")
