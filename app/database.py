from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

database_url = make_url(settings.DATABASE_URL)
pool_options = {}
if database_url.get_backend_name() == "postgresql":
    pool_options = {"pool_size": settings.DATABASE_POOL_SIZE, "max_overflow": settings.DATABASE_MAX_OVERFLOW}
engine = create_engine(database_url, pool_pre_ping=True, hide_parameters=True, **pool_options)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()


def initialize_schema(engine):
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if engine.dialect.name == "sqlite" and not tables:
        Base.metadata.create_all(bind=engine)
        return

    for table in Base.metadata.sorted_tables:
        if table.name not in tables or not set(table.columns.keys()).issubset(
            column["name"] for column in inspector.get_columns(table.name)
        ):
            raise RuntimeError("TraceGrid database schema is out of date. Run alembic upgrade head before starting.")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
