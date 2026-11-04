from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class CustomerBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="Customer full name")
    phone: str | None = Field(None, max_length=50, description="Optional mobile/phone number")
    email: EmailStr | None = Field(None, description="Optional email address")
    address: str | None = Field(None, description="Optional physical address")
    notes: str | None = Field(None, description="Optional customer notes")


class CustomerCreate(CustomerBase):
    pass


class CustomerUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    phone: str | None = Field(None, max_length=50)
    email: EmailStr | None = None
    address: str | None = None
    notes: str | None = None


class CustomerResponse(CustomerBase):
    model_config = ConfigDict(from_attributes=True)

    customer_id: UUID
    store_id: UUID
    created_at: datetime
    updated_at: datetime
    total_orders: int = 0
    total_spent: Decimal = Decimal("0.00")
    last_order_date: datetime | None = None
    is_multi_store: bool = False
    store_ids: list[UUID] = Field(default_factory=list)


class CustomerTransactionHistoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    transaction_id: UUID
    invoice_number: str
    invoice_seq: int | None = None
    store_id: UUID | None = None
    store_name: str | None = None
    final_total: Decimal
    received_amount: Decimal = Decimal("0.00")
    balance_amount: Decimal = Decimal("0.00")
    payment_method: str
    payment_status: str
    items_count: int = 0
    created_at: datetime


class CustomerHistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    customer: CustomerResponse
    transactions: list[CustomerTransactionHistoryItem]
    total_orders: int = 0
    total_spent: Decimal = Decimal("0.00")
    all_stores_orders: int | None = None
    all_stores_spent: Decimal | None = None
