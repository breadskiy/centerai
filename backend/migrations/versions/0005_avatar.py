"""Store a normalized account avatar."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"


def upgrade():
    op.add_column("accounts", sa.Column("avatar", sa.LargeBinary()))


def downgrade():
    op.drop_column("accounts", "avatar")
