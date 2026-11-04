import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_active_user, get_current_store_context
from app.models.user import User
from app.schemas.customer import (
    CustomerCreate,
    CustomerHistoryResponse,
    CustomerResponse,
    CustomerUpdate,
)
from app.services.customer_service import CustomerService

router = APIRouter(prefix="/customers", tags=["Store Customers Directory"])


@router.get(
    "",
    response_model=list[CustomerResponse],
    summary="List and Search Store Customers Directory (Phone Book)",
)
def list_customers(
    search: str | None = Query(None, description="Search customers by name or phone number"),
    sort_by: str = Query("recent", description="Sorting criteria: 'recent', 'name', 'orders', or 'spent'"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    store_id: uuid.UUID = Depends(get_current_store_context),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Returns the store's customer directory (phone book) with metrics like total purchases,
    total amount spent, and last purchase date. Strictly isolated to active store tenant.
    """
    return CustomerService.list_customers(
        db=db,
        store_id=store_id,
        search=search,
        sort_by=sort_by,
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    response_model=CustomerResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add New Customer to Store Directory",
)
def create_customer(
    customer_in: CustomerCreate,
    store_id: uuid.UUID = Depends(get_current_store_context),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Adds a new customer profile with name and optional mobile number to the active store.
    """
    return CustomerService.create_customer(
        db=db,
        store_id=store_id,
        customer_in=customer_in,
    )


@router.get(
    "/{customer_id}",
    response_model=CustomerResponse,
    summary="Get Customer Details by ID",
)
def get_customer(
    customer_id: uuid.UUID,
    store_id: uuid.UUID = Depends(get_current_store_context),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Retrieves full customer details including purchase statistics for the active store tenant.
    """
    return CustomerService.get_customer_by_id(
        db=db,
        customer_id=customer_id,
        store_id=store_id,
    )


@router.get(
    "/{customer_id}/history",
    response_model=CustomerHistoryResponse,
    summary="Get Customer Purchase & Bill History",
)
def get_customer_history(
    customer_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    store_id: uuid.UUID = Depends(get_current_store_context),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Retrieves all past transactions and invoices for a specific customer in this store.
    """
    return CustomerService.get_customer_history(
        db=db,
        customer_id=customer_id,
        store_id=store_id,
        limit=limit,
        offset=offset,
    )


@router.put(
    "/{customer_id}",
    response_model=CustomerResponse,
    summary="Update Customer Profile Information",
)
def update_customer(
    customer_id: uuid.UUID,
    customer_update: CustomerUpdate,
    store_id: uuid.UUID = Depends(get_current_store_context),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Updates existing customer details in the active store tenant.
    """
    return CustomerService.update_customer(
        db=db,
        customer_id=customer_id,
        store_id=store_id,
        customer_update=customer_update,
    )
