import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_active_user, get_current_store_context
from app.core.exceptions import ForbiddenException
from app.models.user import User
from app.schemas.billing import (
    OfflineSyncRequest,
    OfflineSyncResponse,
    POSTransactionCreate,
    ReceiptResponse,
    StockValidationRequest,
    StockValidationResponse,
    TransactionResponse,
)
from app.services.pos_service import POSService

router = APIRouter(prefix="/billing", tags=["Billing & Point-of-Sale (POS)"])


@router.post(
    "/sync",
    response_model=OfflineSyncResponse,
    summary="Synchronize Batch of Offline POS Transactions",
)
def sync_offline_transactions(
    req: OfflineSyncRequest,
    store_id: uuid.UUID = Depends(get_current_store_context),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Synchronizes offline captured POS transactions with atomic FEFO stock deduction
    and client_offline_id idempotency check.
    """
    if req.store_id and req.store_id != store_id:
        raise ForbiddenException("Cannot sync transactions for another store tenant.")
    return POSService.sync_offline_transactions(
        db=db,
        store_id=store_id,
        cashier=current_user,
        sync_req=req,
    )


@router.post(
    "/validate-stock",
    response_model=StockValidationResponse,
    summary="Pre-validate Cart Stock Before Proceeding to Checkout",
)
def validate_cart_stock(
    req: StockValidationRequest,
    store_id: uuid.UUID = Depends(get_current_store_context),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Checks active non-depleted stock for items in the cart in real-time.
    Returns whether stock is sufficient and any item-specific discrepancies.
    """
    return POSService.validate_cart_stock(db=db, store_id=store_id, items=req.items)


@router.post(
    "/checkout",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Execute POS Checkout (Atomic FEFO Stock Deduction & 3-Tier Discounts)",
)
@router.post(
    "/transactions",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
def checkout(
    pos_in: POSTransactionCreate,
    store_id: uuid.UUID = Depends(get_current_store_context),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Core POS Checkout Loop:
    1. Validates cart items and calculates Base Total (Quantity * UnitPrice).
    2. Applies priority discounts (Item Level -> Category Level -> Total Level).
    3. Performs atomic FEFO stock deduction across batches (raises 400 if insufficient stock).
    4. Generates unique invoice and records detailed batch allocation audit trail.
    5. Dispatches async alerts if stock drops below threshold.
    Enforces strict tenant isolation.
    """
    if pos_in.store_id and pos_in.store_id != store_id:
        raise ForbiddenException("Cannot execute checkout for another store tenant.")

    tx = POSService.process_pos_transaction(
        db=db,
        store_id=store_id,
        cashier=current_user,
        pos_in=pos_in,
    )
    return POSService.to_transaction_response(tx)


@router.get(
    "/transactions",
    response_model=list[TransactionResponse],
    summary="List Transactions for Active Store Tenant with Search & Date Filters",
)
def list_transactions(
    search: str | None = Query(None, description="Search by invoice number, customer name, or phone"),
    date_filter: str | None = Query(None, description="Preset date filter: 'today', 'yesterday', 'this_week', 'this_month'"),
    start_date: date | None = Query(None, description="Custom start date (YYYY-MM-DD)"),
    end_date: date | None = Query(None, description="Custom end date (YYYY-MM-DD)"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    store_id: uuid.UUID = Depends(get_current_store_context),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Lists finalized transactions strictly for the active store tenant.
    Supports real-time search (invoice #, customer name, phone) and date-based filtering.
    """
    txs = POSService.list_transactions(
        db,
        store_id=store_id,
        search=search,
        date_filter=date_filter,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )
    return [POSService.to_transaction_response(tx) for tx in txs]


@router.get(
    "/transactions/{transaction_id}",
    response_model=TransactionResponse,
    summary="Get Transaction Details by ID",
)
def get_transaction(
    transaction_id: uuid.UUID,
    store_id: uuid.UUID = Depends(get_current_store_context),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Retrieves complete transaction entity including line items and FEFO batch allocations.
    Strictly isolated to active store tenant.
    """
    tx = POSService.get_transaction_by_id(db, transaction_id, store_id=store_id)
    return POSService.to_transaction_response(tx)


@router.get(
    "/transactions/{transaction_id}/receipt",
    response_model=ReceiptResponse,
    summary="Get Raw Structured Receipt Data (For Client-Side PDF & Android PrintManager)",
)
def get_transaction_receipt(
    transaction_id: uuid.UUID,
    store_id: uuid.UUID = Depends(get_current_store_context),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Returns complete structured receipt data for the transaction.
    Meets Section 3.2 specification: Provides all raw metadata, formatted line items,
    discount breakdowns, store header, and authorized signature base64 so that
    the React Native client can render the PDF and print via Android PrintManager.
    Strictly isolated to active store tenant.
    """
    return POSService.get_receipt_data(db, transaction_id, store_id=store_id)
