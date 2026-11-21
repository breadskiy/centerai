"""Add accounts and isolate stored workspaces."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"


def upgrade():
    op.create_table(
        "accounts",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("email", sa.String(254), unique=True),
        sa.Column("password_hash", sa.String()),
        sa.Column("nickname", sa.String(60), nullable=False),
        sa.Column("telegram_username", sa.String(32), nullable=False),
        sa.Column("guest_until", sa.Float()),
    )
    op.create_index("ix_accounts_guest_until", "accounts", ["guest_until"])
    op.create_table(
        "auth_sessions",
        sa.Column("digest", sa.String(64), primary_key=True),
        sa.Column(
            "account_id", sa.String(32), sa.ForeignKey("accounts.id"), nullable=False
        ),
        sa.Column("expires_at", sa.Float(), nullable=False),
    )
    op.create_index("ix_auth_sessions_account_id", "auth_sessions", ["account_id"])
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])
    if op.get_bind().dialect.name == "sqlite":
        op.execute(
            "ALTER TABLE projects ADD COLUMN owner_id VARCHAR(32) REFERENCES accounts(id)"
        )
    else:
        op.add_column("projects", sa.Column("owner_id", sa.String(32)))
        op.create_foreign_key(
            "fk_projects_owner_id", "projects", "accounts", ["owner_id"], ["id"]
        )
    op.create_index("ix_projects_owner_id", "projects", ["owner_id"])


def downgrade():
    op.drop_index("ix_projects_owner_id", table_name="projects")
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint("fk_projects_owner_id", "projects", type_="foreignkey")
    op.drop_column("projects", "owner_id")
    op.drop_table("auth_sessions")
    op.drop_table("accounts")
