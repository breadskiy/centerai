"""Give each GitHub identity a single CenterAI owner."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"


def upgrade():
    op.add_column("accounts", sa.Column("github_id", sa.String(32)))
    op.add_column("accounts", sa.Column("github_login", sa.String(100)))
    op.create_index("uq_accounts_github_id", "accounts", ["github_id"], unique=True)


def downgrade():
    op.drop_index("uq_accounts_github_id", table_name="accounts")
    op.drop_column("accounts", "github_login")
    op.drop_column("accounts", "github_id")
