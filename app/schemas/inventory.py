from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.inventory import UnitEnum


class ProductBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="Product title")
    description: str | None = Field(None, description="Detailed product description")
    category: str = Field("General", min_length=1, max_length=100, description="Product category for POS grouping and discounts")
    default_unit: UnitEnum = Field(UnitEnum.PIECE, description="Measurement unit (KG, ML, GRAM, DOZEN, PIECE, etc.)")
    selling_price: Decimal = Field(..., gt=Decimal("0.00"), description="Default retail selling price")
    cost_price: Decimal = Field(Decimal("0.00"), ge=Decimal("0.00"), description="Acquisition cost price per unit")
    min_stock_alert_threshold: Decimal = Field(
        Decimal("10.000"),
        ge=Decimal("0.000"),
        description="Minimum inventory count before low stock alert is triggered",
    )
    barcode: str | None = Field(None, max_length=100, description="UPC/EAN or Barcode string")


class ProductCreate(ProductBase):
    store_id: UUID | None = Field(None, description="Store ID. Defaults to user's active store context.")


class ProductUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    category: str | None = Field(None, min_length=1, max_length=100)
    default_unit: UnitEnum | None = None
    selling_price: Decimal | None = Field(None, gt=Decimal("0.00"))
    cost_price: Decimal | None = Field(None, ge=Decimal("0.00"))
    min_stock_alert_threshold: Decimal | None = Field(None, ge=Decimal("0.000"))
    barcode: str | None = Field(None, max_length=100)
    is_active: bool | None = None


class BatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    batch_id: UUID
    product_id: UUID
    store_id: UUID
    batch_identifier: str
    initial_quantity: Decimal
    current_quantity: Decimal
    purchase_price: Decimal
    expiry_date: date
    purchase_date: date
    days_to_expiry: int
    is_expired: bool
    created_at: datetime


class ProductResponse(ProductBase):
    model_config = ConfigDict(from_attributes=True)

    product_id: UUID
    store_id: UUID
    total_current_stock: Decimal = Field(Decimal("0.000"), description="Computed real-time sum of current_quantity across active batches")
    is_active: bool
    created_at: datetime
    updated_at: datetime
    batches: list[BatchResponse] | None = []


class CategorySummaryResponse(BaseModel):
    name: str = Field(..., description="Category name")
    count: int = Field(0, description="Total active products in category for this store tenant")


class BatchReceiveSingle(BaseModel):
    store_id: UUID | None = Field(None, description="Target store ID. Defaults to active store context.")
    product_id: UUID = Field(..., description="ID of the product receiving stock")
    batch_identifier: str = Field(..., min_length=1, max_length=100, description="Supplier lot or batch identifier")
    quantity: Decimal = Field(..., gt=Decimal("0.000"), description="Quantity received")
    purchase_price: Decimal = Field(Decimal("0.00"), ge=Decimal("0.00"), description="Cost price per unit for this batch")
    purchase_date: date = Field(default_factory=date.today, description="Date batch was acquired")
    expiry_date: date = Field(..., description="Crucial expiration date for FEFO stock rotation")

    @model_validator(mode="after")
    def validate_dates(self):
        if self.expiry_date < self.purchase_date:
            raise ValueError(f"expiry_date ({self.expiry_date}) cannot be earlier than purchase_date ({self.purchase_date})")
        return self


class BatchBulkItem(BaseModel):
    product_id: UUID = Field(..., description="ID of the product receiving stock")
    batch_identifier: str = Field(..., min_length=1, max_length=100, description="Supplier lot or batch identifier")
    quantity: Decimal = Field(..., gt=Decimal("0.000"), description="Quantity received")
    purchase_price: Decimal = Field(Decimal("0.00"), ge=Decimal("0.00"), description="Purchase price per unit")
    purchase_date: date = Field(default_factory=date.today, description="Purchase date")
    expiry_date: date = Field(..., description="Expiry date")

    @model_validator(mode="after")
    def validate_dates(self):
        if self.expiry_date < self.purchase_date:
            raise ValueError(f"expiry_date ({self.expiry_date}) cannot be earlier than purchase_date ({self.purchase_date})")
        return self


class BatchReceiveBulk(BaseModel):
    store_id: UUID | None = Field(None, description="Target store ID. Defaults to active store context.")
    batches: list[BatchBulkItem] = Field(..., min_length=1, description="List of batches to ingest atomically")
