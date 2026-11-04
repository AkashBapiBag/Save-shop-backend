import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_active_user, get_current_store_context
from app.models.user import User
from app.schemas.customer import (
    CustomerCreate,
    CustomerHistoryResponse,
    CustomerPaymentCreate,
    CustomerPaymentResponse,
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
    sort_by: str = Query("recent", description="Sorting criteria: 'recent', 'name', 'orders', 'spent', or 'dues'"),
    filter_dues: bool = Query(False, description="Filter to only customers with outstanding due balances"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    store_id: uuid.UUID = Depends(get_current_store_context),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Returns the store's customer directory (phone book) with metrics like total purchases,
    total amount spent, total dues, and last purchase date. Strictly isolated to active store tenant.
    """
    return CustomerService.list_customers(
        db=db,
        store_id=store_id,
        search=search,
        sort_by=sort_by,
        filter_dues=filter_dues,
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
    Retrieves full customer details including purchase and due statistics for the active store tenant.
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
    Retrieves all past transactions, invoices, and payment settlements for a customer.
    """
    return CustomerService.get_customer_history(
        db=db,
        customer_id=customer_id,
        store_id=store_id,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/{customer_id}/payments",
    response_model=CustomerPaymentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record Customer Due Clearance / Advance Payment",
)
def record_customer_payment(
    customer_id: uuid.UUID,
    payment_in: CustomerPaymentCreate,
    store_id: uuid.UUID = Depends(get_current_store_context),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Records a payment made by a customer to clear outstanding dues or add advance store credit.
    Automatically applies payment FIFO across oldest pending transactions.
    """
    return CustomerService.record_payment(
        db=db,
        store_id=store_id,
        customer_id=customer_id,
        payment_in=payment_in,
        cashier=current_user,
    )


@router.get(
    "/{customer_id}/payments",
    response_model=list[CustomerPaymentResponse],
    summary="List Customer Payment Settlement Receipts",
)
def list_customer_payments(
    customer_id: uuid.UUID,
    store_id: uuid.UUID = Depends(get_current_store_context),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Retrieves all past settlement receipts for a specific customer in this store.
    """
    return CustomerService.list_customer_payments(
        db=db,
        store_id=store_id,
        customer_id=customer_id,
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
