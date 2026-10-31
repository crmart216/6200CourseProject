from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


@lru_cache
def get_session_factory():
    engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    return sessionmaker(bind=engine, expire_on_commit=False)


def get_db():
    # Controllers commit writes; exceptions always roll back at the request boundary.
    with get_session_factory()() as session:
        try:
            yield session
        except Exception:
            session.rollback()
            raise
