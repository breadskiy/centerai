"""Verify account emails and persist report delivery jobs."""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"


def upgrade():
    op.add_column("accounts", sa.Column("email_verified_at", sa.Float()))
    op.add_column("accounts", sa.Column("pending_email", sa.String(254)))
    op.add_column("accounts", sa.Column("email_verification_digest", sa.String(64)))
    op.add_column("accounts", sa.Column("email_verification_sent_at", sa.Float()))
    op.create_table(
        "report_emails",
        sa.Column(
            "run_id",
            sa.String(32),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("recipient", sa.String(254)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("due", sa.Float(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error", sa.String()),
    )
    op.create_index("ix_report_emails_status", "report_emails", ["status"])


def downgrade():
    op.drop_table("report_emails")
    for column in (
        "email_verification_sent_at",
        "email_verification_digest",
        "pending_email",
        "email_verified_at",
    ):
        op.drop_column("accounts", column)
