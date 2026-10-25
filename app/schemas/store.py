from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class IndianStateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    state_type: str
    display_name: str


class StoreCreate(BaseModel):
    store_id: UUID | None = Field(
        None,
        description="Optional pre-determined UUID for the store. Pre-save check will verify zero transactions exist.",
    )
    name: str = Field(..., min_length=2, max_length=255, description="Unique store name")
    owner_name: str | None = Field(None, max_length=255, description="Name of store owner / proprietor")
    phone_number: str | None = Field(None, max_length=50, description="Store contact phone number")
    address: str | None = Field(None, description="Store physical street address")
    state: str | None = Field("19-West Bengal", max_length=100, description="Indian State / UT code and name")
    email: EmailStr | None = Field(None, description="Store official email address")
    logo_url: str | None = Field(None, max_length=1024, description="S3 / Cloud storage logo URL")
    logo_base64: str | None = Field(None, description="Base64 encoded 1:1 square store logo image")
    authorized_signature_base64: str | None = Field(
        None,
        description="Base64 encoded authorized signature image (stored as BYTEA/BLOB)",
    )


class StoreUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=255)
    owner_name: str | None = Field(None, max_length=255)
    phone_number: str | None = Field(None, max_length=50)
    address: str | None = None
    state: str | None = Field(None, max_length=100)
    email: EmailStr | None = None
    logo_url: str | None = Field(None, max_length=1024)
    logo_base64: str | None = None
    authorized_signature_base64: str | None = None
    is_active: bool | None = None


class StoreResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    store_id: UUID
    name: str
    owner_name: str | None = None
    phone_number: str | None = None
    address: str | None = None
    state: str = "19-West Bengal"
    email: str | None = None
    logo_url: str | None = None
    has_logo: bool = False
    logo_base64: str | None = None
    has_signature: bool = False
    authorized_signature_base64: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SignatureUploadRequest(BaseModel):
    signature_base64: str = Field(
        ...,
        min_length=10,
        description="Base64 encoded string containing the authorized signatory image",
    )


class SignatureResponse(BaseModel):
    store_id: UUID
    has_signature: bool
    signature_base64: str | None = None
