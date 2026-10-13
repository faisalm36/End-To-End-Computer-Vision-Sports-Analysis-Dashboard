"""SQLAlchemy engine, session factory and declarative Base."""
from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config import settings

_connect_args: dict = {}
_is_sqlite = settings.DATABASE_URL.startswith("sqlite")
if settings.DATABASE_URL.startswith("mysql"):
    # Fail fast (instead of hanging) when MySQL is down; keep utf8mb4.
    _connect_args = {"connect_timeout": 3, "charset": "utf8mb4"}
elif _is_sqlite:
    _connect_args = {"check_same_thread": False}

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    echo=settings.SQL_ECHO,
    connect_args=_connect_args,
)

if _is_sqlite:  # tests: enforce FKs / ON DELETE CASCADE like MySQL does
    @event.listens_for(engine, "connect")
    def _sqlite_fk_on(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

if settings.DATABASE_URL.startswith("mysql"):
    # All DATETIME values are stored as naive UTC: make CURRENT_TIMESTAMP / NOW() return UTC in every session.
    @event.listens_for(engine, "connect")
    def _mysql_utc(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("SET time_zone = '+00:00'")
        cur.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a DB session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
