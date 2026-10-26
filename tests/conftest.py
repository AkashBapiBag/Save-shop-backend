import os

os.environ["ENVIRONMENT"] = "testing"
os.environ["ENABLE_DEV_DIRECT_LOGIN"] = "true"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app

# Use an in-memory SQLite database for isolated test execution
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    # Seed reference tables in SQLite test database
    import json

    from app.models.state import IndianState

    seed_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app", "db", "seeds", "indian_states.json")
    if os.path.exists(seed_file):
        with open(seed_file, encoding="utf-8") as f:
            states_data = json.load(f)
        session = TestingSessionLocal()
        for st in states_data:
            session.add(
                IndianState(
                    code=st["code"],
                    name=st["name"],
                    state_type=st["state_type"],
                    display_name=st["display_name"],
                )
            )
        session.commit()
        session.close()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    """
    Creates a fresh database session for a test with rolled-back state.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def admin_headers():
    return {"X-Dev-User-Email": "admin@saveshop.com"}


@pytest.fixture
def standard_user_headers(client):
    # Ensure standard user exists
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "clerk@saveshop.com", "name": "Clerk User", "role": "user"},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]
    return {
        "Authorization": f"Bearer {token}",
        "X-Dev-User-Email": "clerk@saveshop.com",
    }
