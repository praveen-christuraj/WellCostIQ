from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


url = get_settings().database_url
engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {}, pool_pre_ping=True)
if url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
elif url.startswith("postgresql"):
    @event.listens_for(engine, "connect")
    def bound_postgresql_session(dbapi_connection, connection_record):
        """Bound stuck work without requiring ALTER ROLE administrator rights.

        These session limits also protect hosted databases whose pooler role
        cannot alter role defaults. Imports still have their existing request
        window; an individual SQL statement is capped at 120 seconds by design.
        """
        cursor = dbapi_connection.cursor()
        cursor.execute("SET SESSION statement_timeout = 120000")
        cursor.execute("SET SESSION idle_in_transaction_session_timeout = 60000")
        cursor.execute("SET SESSION lock_timeout = 10000")
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    with SessionLocal() as db:
        yield db
