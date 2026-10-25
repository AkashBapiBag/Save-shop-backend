from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.user import UserRole


class LoginRequest(BaseModel):
    # Google SSO Tokens
    id_token: str | None = Field(None, description="Google ID Token (JWT)")
    access_token: str | None = Field(None, description="Google OAuth Access Token")
    google_token: str | None = Field(None, description="Google SSO ID or Access Token")
    # For legacy Auth0 SSO
    auth0_token: str | None = Field(None, description="Auth0 ID or Access Token")
    # For automated test suites / test fixtures
    email: EmailStr | None = Field(None, description="Test email for mock login")
    name: str | None = Field("User", description="Display name for user")
    role: UserRole | None = Field(UserRole.ADMIN, description="Role to assume in test mode")


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    email: EmailStr
    name: str
    role: str
    picture_url: str | None = None
    current_store_id: UUID | None = None
    accessible_store_ids: list[UUID] = []
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class StoreSwitchRequest(BaseModel):
    store_id: UUID = Field(..., description="Target Store ID to switch active context to")


class AssignStoreRequest(BaseModel):
    user_id: UUID = Field(..., description="Standard user ID to grant store access to")
    store_id: UUID = Field(..., description="Store ID")
