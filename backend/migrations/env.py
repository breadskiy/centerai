from alembic import context
from backend.db import Base, engine

with engine.begin() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
