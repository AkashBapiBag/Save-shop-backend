import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_active_user, get_current_store_context
from app.models.user import User
from app.schemas.dashboard import (
    DashboardOverviewResponse,
    InventoryStatusResponse,
    SalesVelocityResponse,
    StockHealthResponse,
)
from app.services.dashboard_service import DashboardService

router = APIRouter(prefix="/dashboard", tags=["Dashboard & Reporting"])


@router.get(
    "/overview",
    response_model=DashboardOverviewResponse,
    summary="Dashboard Overview KPIs (Revenue, Sales Count, Low Stock, Expiry Counts)",
)
def get_dashboard_overview(
    store_id: uuid.UUID = Depends(get_current_store_context),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Returns real-time aggregated metrics for the store:
    - Today's, weekly, and monthly revenue
    - Transaction counts
    - Total active products
    - Low stock alerts count
    - Expiries within 30 & 60 days
    """
    return DashboardService.get_overview(db, store_id)


@router.get(
    "/stock-health",
    response_model=StockHealthResponse,
    summary="Stock Health: Batches Nearing Expiry (30/60 Days) and Expired",
)
def get_stock_health(
    store_id: uuid.UUID = Depends(get_current_store_context),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Returns products and batches categorized into EXPIRED, CRITICAL_30_DAYS, and WARNING_60_DAYS.
    """
    return DashboardService.get_stock_health(db, store_id)


@router.get(
    "/sales-velocity",
    response_model=SalesVelocityResponse,
    summary="Sales Velocity: Top Selling Items and Daily Trends",
)
def get_sales_velocity(
    period_days: int = Query(7, ge=1, le=90, description="Analysis window in days (default: 7)"),
    top_n: int = Query(5, ge=1, le=50, description="Top N items (default: 5)"),
    store_id: uuid.UUID = Depends(get_current_store_context),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Calculates top selling products by units and revenue, alongside day-by-day revenue trends.
    """
    return DashboardService.get_sales_velocity(db, store_id, period_days=period_days, top_n=top_n)


@router.get(
    "/inventory-status",
    response_model=InventoryStatusResponse,
    summary="Inventory Status: Stock Levels and Alerts",
)
def get_inventory_status(
    store_id: uuid.UUID = Depends(get_current_store_context),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Provides immediate visibility into low-stock and out-of-stock products.
    """
    return DashboardService.get_inventory_status(db, store_id)
