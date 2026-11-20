from pathlib import Path
from alembic import command
from alembic.config import Config


def upgrade():
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).with_name("migrations")))
    command.upgrade(config, "head")


if __name__ == "__main__":
    upgrade()
