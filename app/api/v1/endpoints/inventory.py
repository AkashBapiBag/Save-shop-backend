import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_active_user, get_current_store_context
from app.core.exceptions import ForbiddenException
from app.models.user import User
from app.schemas.inventory import (
    BatchReceiveBulk,
    BatchReceiveSingle,
    BatchResponse,
    CategorySummaryResponse,
    ProductCreate,
    ProductResponse,
    ProductUpdate,
)
from app.services.inventory_service import InventoryService

router = APIRouter(prefix="/inventory", tags=["Inventory & Batch Tracking"])


@router.post(
    "/products",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Product in Active Store",
)
def create_product(
    product_in: ProductCreate,
    store_id: uuid.UUID = Depends(get_current_store_context),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Registers a new product entity in the active store catalog.
    Enforces strict tenant isolation: Products can only be created in the authorized store context.
    """
    if product_in.store_id and product_in.store_id != store_id:
        raise ForbiddenException("Cannot create a product for another store tenant.")

    product = InventoryService.create_product(db, store_id, product_in)
    return InventoryService.to_product_response(product)


@router.get(
    "/categories",
    response_model=list[CategorySummaryResponse],
    summary="List Categories with Counts for Active Store Tenant",
)
def list_categories(
    store_id: uuid.UUID = Depends(get_current_store_context),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Returns unique categories and product counts strictly scoped to the active store tenant.
    Guarantees no categories are shared between store tenants.
    """
    return InventoryService.list_categories(db, store_id)


@router.get(
    "/products",
    response_model=list[ProductResponse],
    summary="List Products with Computed Stock Levels",
)
def list_products(
    category: str | None = Query(None, description="Filter by category"),
    search: str | None = Query(None, description="Search by name or barcode"),
    store_id: uuid.UUID = Depends(get_current_store_context),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Lists products with real-time stock computed by aggregating active positive batches.
    """
    results = InventoryService.list_products(db, store_id, category=category, search=search)
    return [InventoryService.to_product_response(prod, total_stock) for prod, total_stock in results]


@router.get(
    "/products/{product_id}",
    response_model=ProductResponse,
    summary="Get Product by ID with Batch Breakdown",
)
def get_product(
    product_id: uuid.UUID,
    store_id: uuid.UUID = Depends(get_current_store_context),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Retrieves product details along with its individual batch instances.
    """
    product = InventoryService.get_product(db, product_id, store_id)
    return InventoryService.to_product_response(product)


@router.put(
    "/products/{product_id}",
    response_model=ProductResponse,
    summary="Update Product Metadata",
)
def update_product(
    product_id: uuid.UUID,
    product_in: ProductUpdate,
    store_id: uuid.UUID = Depends(get_current_store_context),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Updates product information (price, name, category, alert threshold, etc.).
    """
    updated = InventoryService.update_product(db, product_id, product_in, store_id)
    return InventoryService.to_product_response(updated)


@router.post(
    "/receive/single",
    response_model=BatchResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Stock Receiving: Single Batch Ingestion",
)
def receive_single_batch(
    receive_in: BatchReceiveSingle,
    store_id: uuid.UUID = Depends(get_current_store_context),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Atomic operation 1: For one-off batch acquisitions.
    Initializes batch with current_quantity as source of truth.
    Enforces strict tenant isolation.
    """
    if receive_in.store_id and receive_in.store_id != store_id:
        raise ForbiddenException("Cannot receive stock for another store tenant.")

    batch = InventoryService.receive_single_batch(db, store_id, receive_in)
    return InventoryService.to_batch_response(batch)


@router.post(
    "/receive/bulk",
    response_model=list[BatchResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Stock Receiving: Bulk Batches Ingestion",
)
def receive_bulk_batches(
    bulk_in: BatchReceiveBulk,
    store_id: uuid.UUID = Depends(get_current_store_context),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Atomic operation 2: Bulk batch acquisition.
    Requires batch_identifier, quantity, expiry_date, and purchase_date for each batch.
    Committed atomically.
    Enforces strict tenant isolation.
    """
    if bulk_in.store_id and bulk_in.store_id != store_id:
        raise ForbiddenException("Cannot receive stock for another store tenant.")

    batches = InventoryService.receive_bulk_batches(db, store_id, bulk_in)
    return [InventoryService.to_batch_response(b) for b in batches]


@router.get(
    "/batches",
    response_model=list[BatchResponse],
    summary="List Batches for Store",
)
def list_batches(
    product_id: uuid.UUID | None = Query(None, description="Filter by product ID"),
    only_active: bool = Query(True, description="Only batches with current_quantity > 0"),
    store_id: uuid.UUID = Depends(get_current_store_context),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Lists tracked batches in FEFO order (sorted by expiry_date, then purchase_date).
    """
    batches = InventoryService.list_batches(db, store_id, product_id, only_active_stock=only_active)
    return [InventoryService.to_batch_response(b) for b in batches]
