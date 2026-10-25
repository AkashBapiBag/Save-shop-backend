import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_active_user, require_admin, verify_user_store_access
from app.core.exceptions import ForbiddenException
from app.models.user import User
from app.schemas.store import (
    IndianStateResponse,
    SignatureResponse,
    SignatureUploadRequest,
    StoreCreate,
    StoreResponse,
    StoreUpdate,
)
from app.services.store_service import StoreService

router = APIRouter(prefix="/stores", tags=["Store Management"])


@router.post(
    "/create",
    response_model=StoreResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create New Store (Admin Only with Pre-Save Zero-Transaction Check)",
)
@router.post(
    "",
    response_model=StoreResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
def create_store(
    store_in: StoreCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Creates a new store entity.
    - Role Constraint: Only Admin users can initiate store creation.
    - Critical Constraint: A pre-save check (SELECT COUNT(*) FROM transactions WHERE store_id = :new_store_id)
      must confirm zero existing linked data records.
    """
    store = StoreService.create_store(db, store_in, current_user)
    return StoreService.to_response(store)


@router.get(
    "",
    response_model=list[StoreResponse],
    summary="List Stores",
)
def list_stores(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Lists stores accessible to current user (Admins get all; Standard users get authorized stores).
    """
    stores = StoreService.list_stores(db, current_user)
    return [StoreService.to_response(s) for s in stores]


@router.get(
    "/states",
    response_model=list[IndianStateResponse],
    summary="List Indian States and Union Territories",
)
def get_indian_states(
    db: Session = Depends(get_db),
):
    """
    Returns the reference list of 28 States and 8 Union Territories
    in India with their standard official GST State Codes directly from the database.
    """
    return StoreService.get_indian_states(db)


@router.get(
    "/{store_id}",
    response_model=StoreResponse,
    summary="Get Store by ID",
)
def get_store(
    store_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Fetches full metadata for a store instance.
    Enforces tenant access verification for standard users.
    """
    if not verify_user_store_access(db, current_user, store_id):
        raise ForbiddenException(f"You do not have access to store {store_id}.")
    store = StoreService.get_store_by_id(db, store_id)
    return StoreService.to_response(store)


@router.put(
    "/{store_id}",
    response_model=StoreResponse,
    summary="Update Store Metadata (Admin Only)",
)
def update_store(
    store_id: uuid.UUID,
    store_in: StoreUpdate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Updates store operational metadata (name, phone, address, email, logo, etc.).
    """
    if not verify_user_store_access(db, current_user, store_id):
        raise ForbiddenException(f"You do not have access to manage store {store_id}.")
    updated = StoreService.update_store(db, store_id, store_in, current_user)
    return StoreService.to_response(updated)


@router.post(
    "/{store_id}/signature",
    response_model=SignatureResponse,
    summary="Upload Authorized Signatory Data (Admin Only)",
)
def upload_signature(
    store_id: uuid.UUID,
    payload: SignatureUploadRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Securely uploads and saves binary authorized signature data for receipt printing.
    """
    if not verify_user_store_access(db, current_user, store_id):
        raise ForbiddenException(f"You do not have access to manage store {store_id}.")
    store = StoreService.set_store_signature(db, store_id, payload.signature_base64, current_user)
    sig_b64 = StoreService.get_signature_base64(store)
    return SignatureResponse(store_id=store.store_id, has_signature=True, signature_base64=sig_b64)


@router.get(
    "/{store_id}/signature",
    response_model=SignatureResponse,
    summary="Get Authorized Signatory Data",
)
def get_signature(
    store_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Retrieves the base64 authorized signature representation.
    Enforces tenant access verification for standard users.
    """
    if not verify_user_store_access(db, current_user, store_id):
        raise ForbiddenException(f"You do not have access to store {store_id}.")
    store = StoreService.get_store_by_id(db, store_id)
    sig_b64 = StoreService.get_signature_base64(store)
    return SignatureResponse(
        store_id=store.store_id,
        has_signature=store.authorized_signature_data is not None,
        signature_base64=sig_b64,
    )
