import uuid
from datetime import timedelta
from unittest.mock import MagicMock

import jwt
import pytest
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dependencies import (
    get_current_active_user,
    get_current_store_context,
    require_admin,
    verify_user_store_access,
)
from app.core.exceptions import EntityNotFoundException, ForbiddenException, UnauthorizedException
from app.core.security import create_access_token, verify_token
from app.models.store import Store
from app.models.user import User, UserRole, user_store_access


def test_create_and_verify_access_token_hs256():
    payload_data = {"sub": "user-123", "email": "test@domain.com", "role": "admin"}
    token = create_access_token(payload_data, expires_delta=timedelta(minutes=15))
    assert isinstance(token, str)

    decoded = verify_token(token)
    assert decoded["sub"] == "user-123"
    assert decoded["email"] == "test@domain.com"
    assert decoded["role"] == "admin"


def test_verify_token_empty_raises():
    with pytest.raises(UnauthorizedException):
        verify_token("")

    with pytest.raises(UnauthorizedException):
        verify_token(None)


def test_verify_token_malformed_raises():
    with pytest.raises(UnauthorizedException):
        verify_token("not-a-valid-jwt-token-string")


def test_verify_token_auth0_mode(monkeypatch):
    monkeypatch.setattr(settings, "AUTH0_ENABLED", True)
    monkeypatch.setattr(settings, "AUTH0_DOMAIN", "test-tenant.auth0.com")
    monkeypatch.setattr(settings, "AUTH0_API_AUDIENCE", "https://api.saveshop.com")
    monkeypatch.setattr(settings, "AUTH0_ISSUER", "https://test-tenant.auth0.com/")

    # Mock PyJWKClient and decode
    fake_token = "fake.bearer.token"
    mock_client = MagicMock()
    mock_key = MagicMock()
    mock_key.key = "fake-public-key"
    mock_client.get_signing_key_from_jwt.return_value = mock_key

    monkeypatch.setattr("jwt.PyJWKClient", lambda url: mock_client)
    monkeypatch.setattr(
        "jwt.decode",
        lambda tok, key, **kwargs: {"sub": "auth0|999", "email": "auth0user@domain.com", "roles": ["admin"]},
    )

    claims = verify_token(fake_token)
    assert claims["sub"] == "auth0|999"
    assert claims["email"] == "auth0user@domain.com"

    # Test Auth0 verification failure
    def mock_decode_fail(*args, **kwargs):
        raise jwt.PyJWTError("Token signature invalid")

    monkeypatch.setattr("jwt.decode", mock_decode_fail)
    with pytest.raises(UnauthorizedException) as exc_info:
        verify_token(fake_token)
    assert "Invalid Auth0 token" in str(exc_info.value)


def test_require_admin_guard():
    admin = User(user_id=uuid.uuid4(), email="admin@test.com", name="Admin", role=UserRole.ADMIN.value, is_active=True)
    assert require_admin(admin) == admin

    clerk = User(user_id=uuid.uuid4(), email="clerk@test.com", name="Clerk", role=UserRole.USER.value, is_active=True)
    with pytest.raises(ForbiddenException):
        require_admin(clerk)


def test_get_current_active_user_inactive():
    inactive_user = User(user_id=uuid.uuid4(), email="inactive@test.com", name="Inactive", is_active=False)
    with pytest.raises(UnauthorizedException) as exc_info:
        get_current_active_user(inactive_user)
    assert "Inactive user account" in str(exc_info.value)


def test_verify_user_store_access(db_session: Session):
    store_id = uuid.uuid4()
    store = Store(store_id=store_id, name="Access Test Store")
    db_session.add(store)

    admin = User(user_id=uuid.uuid4(), email="adm@test.com", name="Admin", role=UserRole.ADMIN.value)
    clerk = User(user_id=uuid.uuid4(), email="clk@test.com", name="Clerk", role=UserRole.USER.value)
    db_session.add_all([admin, clerk])
    db_session.commit()

    # Admin always has access
    assert verify_user_store_access(db_session, admin, store_id) is True

    # Clerk before assignment -> False
    assert verify_user_store_access(db_session, clerk, store_id) is False

    # Assign clerk to store
    stmt = user_store_access.insert().values(user_id=clerk.user_id, store_id=store_id)
    db_session.execute(stmt)
    db_session.commit()

    # Clerk after assignment -> True
    assert verify_user_store_access(db_session, clerk, store_id) is True


def test_get_current_store_context_invalid_uuid():
    user = User(user_id=uuid.uuid4(), email="u@test.com", name="U", role=UserRole.ADMIN.value, is_active=True)
    with pytest.raises(UnauthorizedException) as exc:
        get_current_store_context(store_id=None, x_store_id="invalid-uuid-string", current_user=user, db=None)
    assert "Invalid X-Store-Id" in str(exc.value)


def test_get_current_store_context_nonexistent_store(db_session: Session):
    random_id = uuid.uuid4()
    admin = User(user_id=uuid.uuid4(), email="adm2@test.com", name="Admin", role=UserRole.ADMIN.value, is_active=True)
    with pytest.raises(EntityNotFoundException):
        get_current_store_context(store_id=random_id, current_user=admin, db=db_session)
