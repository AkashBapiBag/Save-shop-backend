from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class DashboardOverviewResponse(BaseModel):
    store_id: UUID
    store_name: str
    today_transaction_count: int
    today_revenue: Decimal
    weekly_revenue: Decimal
    monthly_revenue: Decimal
    total_active_products: int
    low_stock_products_count: int
    batches_expiring_within_30_days: int
    batches_expiring_within_60_days: int


class CriticalBatchItem(BaseModel):
    batch_id: UUID
    batch_identifier: str
    product_id: UUID
    product_name: str
    category: str
    current_quantity: Decimal
    unit: str
    expiry_date: date
    days_until_expiry: int
    status: str = Field(..., description="'EXPIRED', 'CRITICAL_30_DAYS', or 'WARNING_60_DAYS'")


class StockHealthResponse(BaseModel):
    store_id: UUID
    total_critical_batches: int
    expired_batches_count: int
    expiring_30_days_count: int
    expiring_60_days_count: int
    batches: list[CriticalBatchItem]


class TopSellingProductItem(BaseModel):
    product_id: UUID
    product_name: str
    category: str
    unit: str
    total_quantity_sold: Decimal
    total_revenue: Decimal


class DailyRevenueTrendItem(BaseModel):
    date: str
    transaction_count: int
    revenue: Decimal


class SalesVelocityResponse(BaseModel):
    store_id: UUID
    period_days: int
    top_selling_items: list[TopSellingProductItem]
    daily_trend: list[DailyRevenueTrendItem]


class LowStockAlertItem(BaseModel):
    product_id: UUID
    product_name: str
    category: str
    unit: str
    current_stock: Decimal
    min_stock_alert_threshold: Decimal
    selling_price: Decimal


class InventoryStatusResponse(BaseModel):
    store_id: UUID
    total_products: int
    in_stock_products_count: int
    low_stock_products_count: int
    out_of_stock_products_count: int
    low_stock_items: list[LowStockAlertItem]
    expiring_batches_summary: dict[str, int]
