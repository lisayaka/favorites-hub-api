import os
from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session


def get_database_url() -> str:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL 未配置")
    return database_url


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_database_url(), pool_pre_ping=True)


def get_session() -> Generator[Session, None, None]:
    with Session(get_engine()) as session:
        yield session
