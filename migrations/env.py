import os

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool


def run(connection):
    context.configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("The TraceGrid migration must inspect the existing schema online.")

connection = context.config.attributes.get("connection")
if connection is not None:
    run(connection)
else:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("Set DATABASE_URL in the migration process environment.")
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            run(connection)
    finally:
        engine.dispose()
