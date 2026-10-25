from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.inventory import UnitEnum
from app.models.transaction import PaymentMethod


class POSItemInput(BaseModel):
    product_id: UUID = Field(..., description="ID of product being purchased")
    quantity: Decimal = Field(..., gt=Decimal("0.000"), description="Quantity to purchase")
    unit: UnitEnum | None = Field(None, description="Optional unit override (e.g. GRAM for KG, PIECE for DOZEN)")
    unit_price_override: Decimal | None = Field(None, gt=Decimal("0.00"), description="Optional override for unit price")
    item_discount_pct: Decimal = Field(
        Decimal("0.00"),
        ge=Decimal("0.00"),
        le=Decimal("100.00"),
        description="Percentage discount applied specifically to this item",
    )
    category_discount_pct: Decimal = Field(
        Decimal("0.00"),
        ge=Decimal("0.00"),
        le=Decimal("100.00"),
        description="Optional category discount override for this line item",
    )
    cashback_amount: Decimal | None = Field(
        Decimal("0.00"),
        ge=Decimal("0.00"),
        description="Cashback amount configured on item",
    )
    cashback_pct: Decimal | None = Field(
        Decimal("0.00"),
        ge=Decimal("0.00"),
        le=Decimal("100.00"),
        description="Cashback percentage configured on item",
    )


class CategoryDiscountRule(BaseModel):
    category: str = Field(..., description="Target product category name")
    discount_pct: Decimal = Field(..., ge=Decimal("0.00"), le=Decimal("100.00"), description="Discount percentage for category")


class POSTransactionCreate(BaseModel):
    store_id: UUID | None = Field(None, description="Store ID. Defaults to active user store.")
    items: list[POSItemInput] = Field(..., min_length=1, description="List of cart items")
    category_discounts: list[CategoryDiscountRule] | None = Field(
        default=None,
        description="List of category-level discounts to apply",
    )
    total_discount_pct: Decimal = Field(
        Decimal("0.00"),
        ge=Decimal("0.00"),
        le=Decimal("100.00"),
        description="Final percentage discount applied across the entire subtotal",
    )
    total_discount_amount: Decimal | None = Field(
        Decimal("0.00"),
        ge=Decimal("0.00"),
        description="Fixed amount discount applied across the subtotal",
    )
    discount_type: str | None = Field(
        "percentage",
        description="'percentage' or 'amount'",
    )
    received_amount: Decimal | None = Field(
        None,
        ge=Decimal("0.00"),
        description="Amount received from customer at POS checkout",
    )
    payment_method: PaymentMethod = Field(PaymentMethod.CASH, description="CASH, CARD, UPI, CREDIT")
    customer_name: str | None = Field(None, max_length=255)
    customer_phone: str | None = Field(None, max_length=50)
    customer_email: EmailStr | None = None
    notes: str | None = None
    client_offline_id: str | None = Field(
        None,
        description="Idempotency key for offline transactions captured while mobile device was disconnected",
    )


class BatchAllocationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    allocation_id: UUID
    batch_id: UUID
    batch_identifier: str
    quantity_deducted: Decimal
    expiry_date: date


class TransactionItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    item_id: UUID
    product_id: UUID
    product_name: str
    category: str
    unit: str
    quantity: Decimal
    unit_price: Decimal
    item_discount_pct: Decimal
    category_discount_pct: Decimal
    cashback_amount: Decimal = Decimal("0.00")
    cashback_pct: Decimal = Decimal("0.00")
    discount_amount: Decimal = Decimal("0.00")
    discount_pct: Decimal = Decimal("0.00")
    line_base_total: Decimal
    line_discount_amount: Decimal
    line_total: Decimal
    allocations: list[BatchAllocationResponse] = []


class TransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    transaction_id: UUID
    store_id: UUID
    invoice_number: str
    invoice_seq: int | None = None
    cashier_id: UUID | None = None
    cashier_name: str | None = None
    customer_name: str | None = None
    customer_phone: str | None = None
    customer_email: str | None = None
    subtotal: Decimal
    item_discount_amount: Decimal
    category_discount_amount: Decimal
    total_discount_percentage: Decimal
    total_discount_amount: Decimal
    total_cashback_amount: Decimal = Decimal("0.00")
    tax_amount: Decimal
    final_total: Decimal
    received_amount: Decimal = Decimal("0.00")
    balance_amount: Decimal = Decimal("0.00")
    amount_in_words: str | None = None
    you_saved_amount: Decimal = Decimal("0.00")
    payment_method: str
    payment_status: str
    notes: str | None = None
    offline_synced: bool
    client_offline_id: str | None = None
    created_at: datetime
    items: list[TransactionItemResponse] = []


class StoreReceiptHeader(BaseModel):
    store_id: UUID
    store_name: str
    owner_name: str | None = None
    phone_number: str | None = None
    address: str | None = None
    email: str | None = None
    state: str | None = "19-West Bengal"
    logo_url: str | None = None
    has_logo: bool = False
    logo_base64: str | None = None
    has_signature: bool = False
    authorized_signature_base64: str | None = None


class ReceiptResponse(BaseModel):
    """
    Standardized raw data structure strictly designed for React Native client-side PDF generation
    and native Android PrintManager integration.
    """

    store: StoreReceiptHeader
    invoice_number: str
    invoice_seq: int | None = None
    transaction_id: UUID
    date: datetime
    cashier_name: str | None = "Store Operator"
    customer_name: str | None = "Walk-in Customer"
    customer_phone: str | None = None
    items: list[TransactionItemResponse]
    subtotal: Decimal
    item_discount_amount: Decimal
    category_discount_amount: Decimal
    total_discount_percentage: Decimal
    total_discount_amount: Decimal
    total_cashback_amount: Decimal = Decimal("0.00")
    tax_amount: Decimal
    final_total: Decimal
    received_amount: Decimal = Decimal("0.00")
    balance_amount: Decimal = Decimal("0.00")
    amount_in_words: str | None = None
    you_saved_amount: Decimal = Decimal("0.00")
    payment_method: str
    payment_status: str


class StockValidationItem(BaseModel):
    product_id: UUID
    quantity: Decimal
    unit: UnitEnum | None = Field(None, description="Optional unit override for requested stock")


class StockValidationRequest(BaseModel):
    items: list[StockValidationItem] = Field(..., min_length=1)


class StockValidationItemError(BaseModel):
    product_id: UUID
    product_name: str
    available_stock: Decimal
    requested_stock: Decimal
    message: str


class StockValidationResponse(BaseModel):
    is_valid: bool
    errors: list[StockValidationItemError] = []


class OfflineSyncTransactionResult(BaseModel):
    client_offline_id: str | None = None
    invoice_number: str | None = None
    transaction_id: UUID | None = None
    status: str  # "synced", "already_synced", "failed_insufficient_stock", "failed_error"
    error_message: str | None = None


class OfflineSyncRequest(BaseModel):
    store_id: UUID | None = Field(None, description="Store ID context")
    transactions: list[POSTransactionCreate] = Field(..., min_length=1, description="List of offline captured transactions")


class OfflineSyncResponse(BaseModel):
    total_received: int
    synced_count: int
    already_synced_count: int
    failed_count: int
    results: list[OfflineSyncTransactionResult]
