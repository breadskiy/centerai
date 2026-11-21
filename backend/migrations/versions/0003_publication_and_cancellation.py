"""Keep a published graph version and support cooperative cancellation."""

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"


def upgrade():
    op.add_column(
        "workflow_versions", sa.Column("published_at", sa.Float(), nullable=True)
    )
    op.add_column(
        "runs",
        sa.Column(
            "cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade():
    op.drop_column("runs", "cancel_requested")
    op.drop_column("workflow_versions", "published_at")
