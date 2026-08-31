from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from tradefoundry.bilateral import models as bilateral_models  # noqa: F401
from tradefoundry.config import get_settings
from tradefoundry.controltower import models as controltower_models  # noqa: F401
from tradefoundry.db import Base
from tradefoundry.deals import models as deal_models  # noqa: F401
from tradefoundry.evidence import models as evidence_models  # noqa: F401
from tradefoundry.ingestion import models  # noqa: F401
from tradefoundry.master import models as master_models  # noqa: F401
from tradefoundry.opportunity import models as opportunity_models  # noqa: F401
from tradefoundry.tradealpha import models as tradealpha_models  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", get_settings().database_url)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
