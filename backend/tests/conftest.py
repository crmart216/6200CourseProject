import os

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base, get_db
from app.main import create_app


@pytest.fixture
def client():
    # TEST_DATABASE_URL must reference a dedicated, disposable PostgreSQL database.
    url = os.getenv("TEST_DATABASE_URL")
    if url:
        from app.core.config import get_settings

        old = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = url
        get_settings.cache_clear()
        try:
            command.upgrade(Config("alembic.ini"), "head")
        finally:
            if old is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = old
            get_settings.cache_clear()
        engine = create_engine(url)
    else:
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )

        @event.listens_for(engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(engine)
    # Isolate each test, including controller commits, with an outer transaction.
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )

    def override():
        with factory() as db:
            yield db

    app = create_app()
    app.dependency_overrides[get_db] = override
    with TestClient(app) as test_client:
        yield test_client
    transaction.rollback()
    connection.close()
    engine.dispose()
