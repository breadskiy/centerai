"""Store a separately verified address for report delivery."""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"


def upgrade():
    op.add_column("accounts", sa.Column("report_recipient", sa.String(254)))
    op.add_column(
        "accounts",
        sa.Column(
            "pending_email_reports_only",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade():
    op.drop_column("accounts", "pending_email_reports_only")
    op.drop_column("accounts", "report_recipient")
