import uuid

from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_active_user
from app.models.user import User
from app.schemas.stock_transfer import StockTransferCreate, StockTransferResponse
from app.services.stock_transfer_service import StockTransferService

router = APIRouter(prefix="/inventory/transfers", tags=["Stock Transfers & Inter-Store Inward/Outward"])


@router.post(
    "",
    response_model=StockTransferResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Initiate Inter-Store Stock Transfer",
)
def create_stock_transfer(
    transfer_in: StockTransferCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Executes an atomic stock transfer between two stores:
    1. Validates that current user has administrative/operator access to both stores.
    2. FEFO depletes stock batches from the source store.
    3. Resolves product in destination store:
       - If product exists, receives stock batches.
       - If product does not exist, automatically creates it on-the-go with matching properties.
    4. Records comprehensive audit history for outward and inward tracking.
    """
    transfer = StockTransferService.create_transfer(db, current_user, transfer_in)
    return StockTransferService.to_response(transfer)


@router.get(
    "",
    response_model=list[StockTransferResponse],
    summary="List Stock Transfer History with Inward/Outward Filtering",
)
def list_stock_transfers(
    store_id: uuid.UUID | None = Query(None, description="Filter by store ID"),
    direction: str = Query("all", description="Direction filter: 'all', 'outward', 'inward'"),
    search: str | None = Query(None, description="Search by transfer number, product name, or store name"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    x_store_id: str | None = Header(None, alias="X-Store-Id"),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Returns transfer audit logs.
    Supports filtering by specific store and direction:
    - 'outward': stock transferred out of store
    - 'inward': stock received into store
    - 'all': both directions
    If store_id is not passed in query, falls back to X-Store-Id header.
    """
    target_store_id = store_id
    if not target_store_id and x_store_id:
        try:
            target_store_id = uuid.UUID(x_store_id)
        except ValueError:
            pass

    transfers = StockTransferService.list_transfers(
        db=db,
        current_user=current_user,
        store_id=target_store_id,
        direction=direction,
        search=search,
        limit=limit,
        offset=offset,
    )
    return [StockTransferService.to_response(t) for t in transfers]


@router.get(
    "/{transfer_id}",
    response_model=StockTransferResponse,
    summary="Get Detailed Stock Transfer Audit Record",
)
def get_stock_transfer(
    transfer_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Retrieves full detail of a specific stock transfer transaction including line items and products.
    """
    transfer = StockTransferService.get_transfer(db, current_user, transfer_id)
    return StockTransferService.to_response(transfer)
