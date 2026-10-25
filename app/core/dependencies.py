import uuid

from fastapi import Depends, Header, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import EntityNotFoundException, ForbiddenException, UnauthorizedException
from app.models.store import Store
from app.models.user import User, UserRole, user_store_access
from app.services.auth_service import AuthService

security = HTTPBearer(auto_error=False)


def get_current_user(
    auth: HTTPAuthorizationCredentials | None = Depends(security),
    x_dev_user_email: str | None = Header(None, alias="X-Dev-User-Email"),
    db: Session = Depends(get_db),
) -> User:
    """
    Resolves the authenticated user.
    Enforces Auth0 token verification if present or enabled.
    In local dev mode, allows X-Dev-User-Email header for instant testing.
    """
    if auth and auth.credentials:
        return AuthService.get_or_create_user_from_token(db, auth.credentials)

    # Dev/test mode fallback
    if not settings.AUTH0_ENABLED or settings.ENVIRONMENT in ["development", "testing"]:
        email = x_dev_user_email or "admin@saveshop.com"
        user = db.query(User).filter(User.email == email).first()
        if not user:
            user = User(
                user_id=uuid.uuid4(),
                email=email,
                name="Default Admin User",
                role=UserRole.ADMIN.value,
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        return user

    raise UnauthorizedException("Authorization header with Bearer token is required")


def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_active:
        raise UnauthorizedException("Inactive user account")
    return current_user


def require_admin(
    current_user: User = Depends(get_current_active_user),
) -> User:
    if not current_user.is_admin():
        raise ForbiddenException("Administrative privileges are required for this action.")
    return current_user


def get_current_store_context(
    store_id: uuid.UUID | None = Query(None, description="Target Store ID"),
    x_store_id: str | None = Header(None, alias="X-Store-Id"),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> uuid.UUID:
    """
    Resolves the active store context for the request and validates authorization:
    - Admin can operate on any active store.
    - Standard user is strictly restricted to approved stores.
    """
    target_id = store_id if isinstance(store_id, uuid.UUID) else None
    if not target_id and x_store_id and isinstance(x_store_id, str):
        try:
            target_id = uuid.UUID(x_store_id)
        except ValueError:
            raise UnauthorizedException("Invalid X-Store-Id UUID header") from None

    if not target_id:
        target_id = current_user.current_store_id

    if not target_id:
        # Fallback to user's first accessible store
        accessible = AuthService.get_accessible_stores(db, current_user)
        if accessible:
            target_id = accessible[0].store_id
            current_user.current_store_id = target_id
            db.commit()
        else:
            raise EntityNotFoundException("Store context", "No active or assigned store available.")

    # Verify target store exists and is active
    store = db.query(Store).filter(Store.store_id == target_id, Store.is_active == True).first()
    if not store:
        raise EntityNotFoundException("Store", target_id)

    # Authorization verification
    if not current_user.is_admin():
        has_access = (
            db.query(user_store_access)
            .filter(
                user_store_access.c.user_id == current_user.user_id,
                user_store_access.c.store_id == target_id,
            )
            .first()
        )
        if not has_access:
            raise ForbiddenException(f"You do not have access to store {target_id}.")

    return target_id


def verify_user_store_access(db: Session, user: User, store_id: uuid.UUID) -> bool:
    """
    Checks if a user has access rights to a specific store tenant.
    Admins have global tenant authority; standard users require explicit assignment.
    """
    if user.is_admin():
        return True
    has_access = (
        db.query(user_store_access)
        .filter(
            user_store_access.c.user_id == user.user_id,
            user_store_access.c.store_id == store_id,
        )
        .first()
    )
    return bool(has_access)
