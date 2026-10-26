import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_active_user, require_admin
from app.core.exceptions import UnauthorizedException
from app.models.user import User
from app.schemas.auth import (
    AssignStoreRequest,
    LoginRequest,
    TokenResponse,
    UserResponse,
)
from app.schemas.common import APIResponse
from app.schemas.store import StoreResponse
from app.services.auth_service import AuthService
from app.services.store_service import StoreService

router = APIRouter(prefix="/auth", tags=["Authentication & User Context"])


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="User Login via Google SSO",
)
def login(
    login_in: LoginRequest,
    db: Session = Depends(get_db),
):
    """
    Exchanges Google SSO token for Save Shop session token.
    Direct login without SSO is disabled.
    """
    # 1. Google SSO token exchange
    token = login_in.id_token or login_in.google_token or login_in.access_token
    if token:
        return AuthService.login_with_google(
            db,
            token=token,
            id_token_str=login_in.id_token,
            access_token_str=login_in.access_token,
            picture_url=login_in.picture_url,
            name_override=login_in.name if login_in.name and login_in.name != "User" else None,
        )

    # 2. Legacy Auth0 SSO token exchange if present
    if login_in.auth0_token:
        user = AuthService.get_or_create_user_from_token(db, login_in.auth0_token)
        return TokenResponse(
            access_token=login_in.auth0_token,
            token_type="bearer",
            user=AuthService.build_user_response(user),
        )

    # 3. Only allowed in automated test suites when explicitly enabled
    if (settings.ENVIRONMENT == "testing" or settings.ENABLE_DEV_DIRECT_LOGIN) and login_in.email:
        return AuthService.dev_login(db, login_in)

    raise UnauthorizedException("Direct login without SSO is disabled. Please sign in with Google.")


@router.post(
    "/google",
    response_model=TokenResponse,
    summary="Google SSO Authentication & Token Exchange",
)
def google_sso_login(
    login_in: LoginRequest,
    db: Session = Depends(get_db),
):
    """
    Exchanges a verified Google OAuth ID Token or Access Token for a Save Shop session token.
    """
    token = login_in.id_token or login_in.google_token or login_in.access_token
    if not token:
        raise UnauthorizedException("Google SSO token is required.")
    return AuthService.login_with_google(
        db,
        token=token,
        id_token_str=login_in.id_token,
        access_token_str=login_in.access_token,
        picture_url=login_in.picture_url,
        name_override=login_in.name if login_in.name and login_in.name != "User" else None,
    )


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get Current User Profile & Active Store Context",
)
def get_current_user_profile(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Returns the currently authenticated user's profile, role, and active store.
    """
    AuthService.process_pending_invitations(db, current_user)
    return AuthService.build_user_response(current_user)


@router.get(
    "/stores",
    response_model=list[StoreResponse],
    summary="List Stores Accessible by Current User",
)
def get_accessible_stores(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Admins retrieve all stores; Standard Users retrieve only approved accessible stores.
    """
    stores = AuthService.get_accessible_stores(db, current_user)
    return [StoreService.to_response(s) for s in stores]


@router.post(
    "/switch-store/{store_id}",
    response_model=UserResponse,
    summary="Switch Active Store Context",
)
def switch_store(
    store_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Switches the active store context.
    Enforces authorization: Standard users can only switch to approved stores.
    """
    return AuthService.switch_store(db, current_user, store_id)


@router.post(
    "/assign-store",
    response_model=APIResponse[dict],
    summary="Assign Store Access to Standard User (Admin Only)",
)
def assign_store_access(
    payload: AssignStoreRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Admin grants a Standard User access to a specific store by user_id or email.
    """
    if payload.email:
        res = StoreService.add_store_operator_by_email(
            db, payload.store_id, payload.email, "user", current_user
        )
        return APIResponse(message=res["message"], data={"status": res["status"]})
    elif payload.user_id:
        AuthService.assign_user_to_store(db, payload.user_id, payload.store_id)
        return APIResponse(message="Store access successfully assigned to user.", data={"status": "assigned"})
    else:
        from app.core.exceptions import BadRequestException

        raise BadRequestException("Either user_id or email must be provided.")
