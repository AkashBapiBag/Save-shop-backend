import uuid
from typing import Any

import httpx
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import (
    EntityNotFoundException,
    ForbiddenException,
    UnauthorizedException,
)
from app.core.security import create_access_token, verify_token
from app.models.store import Store
from app.models.user import User, UserRole, user_store_access
from app.schemas.auth import LoginRequest, TokenResponse, UserResponse


class AuthService:
    @staticmethod
    def verify_google_token(
        token: str,
        id_token_str: str | None = None,
        access_token_str: str | None = None,
    ) -> dict[str, Any]:
        """
        Verifies Google SSO token (ID token or OAuth access token).
        Returns profile dict containing: sub, email, name, picture.
        """
        # 1. Automated testing / mock token verification in testing mode
        if (settings.ENVIRONMENT == "testing" or settings.DEBUG) and (
            token.startswith("mock-google-") or token.startswith("test-")
        ):
            parts = token.split(":")
            email = parts[1] if len(parts) > 1 else "google-user@saveshop.com"
            name = parts[2] if len(parts) > 2 else "Google Verified User"
            return {
                "sub": f"mock_google_sub_{uuid.uuid4().hex[:8]}",
                "email": email,
                "email_verified": True,
                "name": name,
                "picture": None,
            }

        candidate_id_token = id_token_str or (token if len(token.split(".")) == 3 else None)
        candidate_access_token = access_token_str or (token if len(token.split(".")) != 3 else None)

        # 2. Try Google ID Token verification via google-auth (Google Cloud OAuth 2.0)
        if candidate_id_token:
            try:
                request = google_requests.Request()
                audience = settings.GOOGLE_CLIENT_ID if settings.GOOGLE_CLIENT_ID else None
                claims = id_token.verify_oauth2_token(candidate_id_token, request, audience=audience)
                return claims
            except Exception:
                pass

            # 3. Fallback: Google Cloud tokeninfo endpoint
            try:
                with httpx.Client(timeout=8.0) as client:
                    resp = client.get(f"https://oauth2.googleapis.com/tokeninfo?id_token={candidate_id_token}")
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get("email"):
                            return data
            except Exception:
                pass

        # 4. Fallback / Access Token: Google OAuth userinfo endpoint with Bearer token
        token_to_try = candidate_access_token or token
        try:
            with httpx.Client(timeout=8.0) as client:
                resp = client.get(
                    "https://www.googleapis.com/oauth2/v3/userinfo",
                    headers={"Authorization": f"Bearer {token_to_try}"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("email"):
                        return data
        except Exception:
            pass

        raise UnauthorizedException("Invalid Google token or token has expired. Please sign in again.")

    @staticmethod
    def login_with_google(
        db: Session,
        token: str,
        id_token_str: str | None = None,
        access_token_str: str | None = None,
    ) -> TokenResponse:
        """
        Authenticates a user via Google SSO. Synchronizes user record in local database.
        """
        google_claims = AuthService.verify_google_token(
            token=token,
            id_token_str=id_token_str,
            access_token_str=access_token_str,
        )
        email = google_claims.get("email")
        if not email:
            raise UnauthorizedException("Google SSO account does not provide an email address.")

        google_sub = str(google_claims.get("sub")) if google_claims.get("sub") else None
        name = google_claims.get("name") or email.split("@")[0]
        picture = google_claims.get("picture")

        # Find existing user by google_sub or email
        user = None
        if google_sub:
            user = db.query(User).filter(User.google_sub == google_sub).first()
        if not user:
            user = db.query(User).filter(User.email == email).first()

        is_admin_email = (
            email.lower() in [e.lower() for e in settings.ADMIN_EMAILS]
            or "admin" in email.lower()
        )

        total_users = db.query(User).count()
        is_first_user = total_users == 0

        if not user:
            role = UserRole.ADMIN.value if (is_first_user or is_admin_email) else UserRole.USER.value
            user = User(
                user_id=uuid.uuid4(),
                google_sub=google_sub,
                email=email,
                name=name,
                picture_url=picture,
                role=role,
                is_active=True,
            )
            # If active store exists and user is admin, set first store as active context
            if role == UserRole.ADMIN.value:
                first_store = db.query(Store).filter(Store.is_active == True).first()
                if first_store:
                    user.current_store_id = first_store.store_id

            db.add(user)
            db.commit()
            db.refresh(user)
        else:
            changed = False
            if google_sub and not user.google_sub:
                user.google_sub = google_sub
                changed = True
            if picture and user.picture_url != picture:
                user.picture_url = picture
                changed = True
            if is_admin_email and user.role != UserRole.ADMIN.value:
                user.role = UserRole.ADMIN.value
                changed = True
            if not user.current_store_id and user.is_admin():
                first_store = db.query(Store).filter(Store.is_active == True).first()
                if first_store:
                    user.current_store_id = first_store.store_id
                    changed = True
            if changed:
                db.commit()
                db.refresh(user)

        # Issue internal JWT token for session
        token_data = {
            "sub": str(user.user_id),
            "email": user.email,
            "role": user.role,
            "name": user.name,
        }
        internal_token = create_access_token(token_data)
        return TokenResponse(
            access_token=internal_token,
            token_type="bearer",
            user=AuthService.build_user_response(user),
        )

    @staticmethod
    def get_or_create_user_from_token(db: Session, token: str) -> User:
        """
        Validates Auth0 SSO token (or dev token) and syncs user into the local database.
        """
        payload = verify_token(token)
        email = payload.get("email") or payload.get("https://saveshop.com/email")
        sub = payload.get("sub")
        name = payload.get("name") or payload.get("nickname") or (email.split("@")[0] if email else "User")

        # Check custom roles from Auth0 claims or default to user
        roles = payload.get("https://saveshop.com/roles") or payload.get("roles") or []
        is_admin_claim = "admin" in [r.lower() for r in roles] if isinstance(roles, list) else False

        if not email:
            # If no email in token, use sub as fallback email
            email = f"{sub or uuid.uuid4().hex[:8]}@saveshop.local"

        user = db.query(User).filter((User.email == email) | (User.auth0_sub == sub)).first()
        if not user:
            user = User(
                user_id=uuid.uuid4(),
                auth0_sub=sub,
                email=email,
                name=name,
                role=UserRole.ADMIN.value if is_admin_claim else UserRole.USER.value,
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        else:
            if is_admin_claim and user.role != UserRole.ADMIN.value:
                user.role = UserRole.ADMIN.value
                db.commit()
                db.refresh(user)
        return user

    @staticmethod
    def dev_login(db: Session, request: LoginRequest) -> TokenResponse:
        """
        Handles local development login without needing external Auth0 connection.
        """
        email = request.email or "admin@saveshop.com"
        name = request.name or "Dev Administrator"
        role = request.role.value if request.role else UserRole.ADMIN.value

        user = db.query(User).filter(User.email == email).first()
        if not user:
            user = User(
                user_id=uuid.uuid4(),
                email=email,
                name=name,
                role=role,
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)

        # Generate internal JWT
        token_data = {
            "sub": str(user.user_id),
            "email": user.email,
            "role": user.role,
            "name": user.name,
        }
        token = create_access_token(token_data)
        return TokenResponse(
            access_token=token,
            token_type="bearer",
            user=AuthService.build_user_response(user),
        )

    @staticmethod
    def switch_store(db: Session, user: User, target_store_id: uuid.UUID) -> UserResponse:
        """
        Switches the user's active store context.
        Enforces role check:
          - Admin can switch to any existing active store.
          - Standard User can ONLY switch to stores they have explicitly been granted access to.
        """
        store = db.query(Store).filter(Store.store_id == target_store_id, Store.is_active == True).first()
        if not store:
            raise EntityNotFoundException("Store", target_store_id)

        if not user.is_admin():
            # Check user_store_access
            has_access = (
                db.query(user_store_access)
                .filter(
                    user_store_access.c.user_id == user.user_id,
                    user_store_access.c.store_id == target_store_id,
                )
                .first()
            )
            if not has_access:
                raise ForbiddenException("You do not have approved access to switch to this store.")

        user.current_store_id = target_store_id
        db.commit()
        db.refresh(user)
        return AuthService.build_user_response(user)

    @staticmethod
    def assign_user_to_store(db: Session, user_id: uuid.UUID, store_id: uuid.UUID) -> bool:
        """
        Grants a standard user access to an approved store. (Admin only action)
        """
        user = db.query(User).filter(User.user_id == user_id).first()
        if not user:
            raise EntityNotFoundException("User", user_id)

        store = db.query(Store).filter(Store.store_id == store_id).first()
        if not store:
            raise EntityNotFoundException("Store", store_id)

        existing = (
            db.query(user_store_access)
            .filter(
                user_store_access.c.user_id == user_id,
                user_store_access.c.store_id == store_id,
            )
            .first()
        )
        if not existing:
            stmt = user_store_access.insert().values(user_id=user_id, store_id=store_id)
            db.execute(stmt)
            # If user has no current store, set this as active
            if not user.current_store_id:
                user.current_store_id = store_id
            db.commit()
        return True

    @staticmethod
    def get_accessible_stores(db: Session, user: User) -> list[Store]:
        """
        Returns all stores accessible to the user:
        - Admin has access to all active stores.
        - Standard user only gets their approved stores.
        """
        if user.is_admin():
            return db.query(Store).filter(Store.is_active == True).all()
        return user.accessible_stores

    @staticmethod
    def build_user_response(user: User) -> UserResponse:
        accessible_ids = [s.store_id for s in user.accessible_stores]
        if user.current_store_id and user.current_store_id not in accessible_ids:
            accessible_ids.append(user.current_store_id)

        return UserResponse(
            user_id=user.user_id,
            email=user.email,
            name=user.name,
            role=user.role,
            picture_url=getattr(user, "picture_url", None),
            current_store_id=user.current_store_id,
            accessible_store_ids=accessible_ids,
            created_at=user.created_at,
        )
