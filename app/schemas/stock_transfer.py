from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StockTransferItemCreate(BaseModel):
    product_id: UUID = Field(..., description="ID of the product in the source store")
    quantity: Decimal = Field(..., gt=Decimal("0.000"), description="Quantity to transfer")


class StockTransferCreate(BaseModel):
    source_store_id: UUID = Field(..., description="Source store transferring out stock")
    destination_store_id: UUID = Field(..., description="Destination store receiving inward stock")
    notes: str | None = Field(None, max_length=1000, description="Optional transfer remarks or justification")
    items: list[StockTransferItemCreate] = Field(..., min_length=1, description="List of items to transfer")


class StockTransferItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    item_id: UUID
    transfer_id: UUID
    source_product_id: UUID | None = None
    destination_product_id: UUID | None = None
    product_name: str
    category: str
    unit: str
    quantity: Decimal
    auto_created_product: bool


class StockTransferResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    transfer_id: UUID
    transfer_number: str
    source_store_id: UUID
    source_store_name: str
    destination_store_id: UUID
    destination_store_name: str
    created_by_user_id: UUID | None = None
    transferred_by_name: str
    status: str
    notes: str | None = None
    total_items: int
    total_quantity: Decimal
    created_at: datetime
    items: list[StockTransferItemResponse] = []
