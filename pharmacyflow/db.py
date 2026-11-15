from functools import lru_cache
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from .config import settings


@lru_cache
def engine(url=None):
    settings().data_dir.mkdir(parents=True, exist_ok=True)
    url = url or settings().database_url
    e = create_engine(
        url,
        connect_args={"check_same_thread": False, "timeout": 30} if url.startswith("sqlite") else {},
        pool_pre_ping=True,
    )
    if url.startswith("sqlite"):

        @event.listens_for(e, "connect")
        def pragmas(conn, _):
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")

    return e


def session(url=None):
    return sessionmaker(engine(url), expire_on_commit=False)()


def get_db():
    with session() as db:
        yield db
