import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.core.exceptions import EntityNotFoundException
from app.models.inventory import Batch, Product
from app.models.store import Store
from app.models.transaction import PaymentStatus, Transaction, TransactionItem
from app.schemas.dashboard import (
    CriticalBatchItem,
    DailyRevenueTrendItem,
    DashboardOverviewResponse,
    InventoryStatusResponse,
    LowStockAlertItem,
    SalesVelocityResponse,
    StockHealthResponse,
    TopSellingProductItem,
)


class DashboardService:
    @staticmethod
    def get_overview(db: Session, store_id: uuid.UUID) -> DashboardOverviewResponse:
        store = db.query(Store).filter(Store.store_id == store_id).first()
        if not store:
            raise EntityNotFoundException("Store", store_id)

        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=7)
        month_start = today_start - timedelta(days=30)
        today_date = date.today()
        date_30 = today_date + timedelta(days=30)
        date_60 = today_date + timedelta(days=60)

        # Revenue & Transaction metrics
        tx_query = db.query(Transaction).filter(
            Transaction.store_id == store_id,
            Transaction.payment_status == PaymentStatus.PAID.value,
        )

        today_txs = tx_query.filter(Transaction.created_at >= today_start).all()
        today_count = len(today_txs)
        today_revenue = sum((tx.final_total for tx in today_txs), Decimal("0.00"))

        week_revenue = (
            db.query(func.coalesce(func.sum(Transaction.final_total), Decimal("0.00")))
            .filter(
                Transaction.store_id == store_id,
                Transaction.payment_status == PaymentStatus.PAID.value,
                Transaction.created_at >= week_start,
            )
            .scalar()
        )

        month_revenue = (
            db.query(func.coalesce(func.sum(Transaction.final_total), Decimal("0.00")))
            .filter(
                Transaction.store_id == store_id,
                Transaction.payment_status == PaymentStatus.PAID.value,
                Transaction.created_at >= month_start,
            )
            .scalar()
        )

        # Products count
        total_products = (
            db.query(Product)
            .filter(
                Product.store_id == store_id,
                Product.is_active == True,
            )
            .count()
        )

        # Low stock count
        products = (
            db.query(Product)
            .filter(
                Product.store_id == store_id,
                Product.is_active == True,
            )
            .all()
        )
        low_stock_count = 0
        for p in products:
            total_stock = sum((b.current_quantity for b in p.batches if b.current_quantity > 0), Decimal("0.000"))
            if total_stock <= p.min_stock_alert_threshold:
                low_stock_count += 1

        # Expiry counts
        batches_30 = (
            db.query(Batch)
            .filter(
                Batch.store_id == store_id,
                Batch.current_quantity > 0,
                Batch.expiry_date <= date_30,
            )
            .count()
        )

        batches_60 = (
            db.query(Batch)
            .filter(
                Batch.store_id == store_id,
                Batch.current_quantity > 0,
                Batch.expiry_date <= date_60,
            )
            .count()
        )

        return DashboardOverviewResponse(
            store_id=store.store_id,
            store_name=store.name,
            today_transaction_count=today_count,
            today_revenue=today_revenue,
            weekly_revenue=Decimal(str(week_revenue or 0)),
            monthly_revenue=Decimal(str(month_revenue or 0)),
            total_active_products=total_products,
            low_stock_products_count=low_stock_count,
            batches_expiring_within_30_days=batches_30,
            batches_expiring_within_60_days=batches_60,
        )

    @staticmethod
    def get_stock_health(db: Session, store_id: uuid.UUID) -> StockHealthResponse:
        store = db.query(Store).filter(Store.store_id == store_id).first()
        if not store:
            raise EntityNotFoundException("Store", store_id)

        today_date = date.today()
        threshold_date = today_date + timedelta(days=60)

        critical_batches = (
            db.query(Batch)
            .join(Product, Batch.product_id == Product.product_id)
            .filter(
                Batch.store_id == store_id,
                Batch.current_quantity > 0,
                Batch.expiry_date <= threshold_date,
            )
            .order_by(Batch.expiry_date.asc())
            .all()
        )

        items: list[CriticalBatchItem] = []
        expired_count = 0
        expiring_30_count = 0
        expiring_60_count = 0

        for b in critical_batches:
            days_left = (b.expiry_date - today_date).days
            if days_left < 0:
                status = "EXPIRED"
                expired_count += 1
            elif days_left <= 30:
                status = "CRITICAL_30_DAYS"
                expiring_30_count += 1
            else:
                status = "WARNING_60_DAYS"
                expiring_60_count += 1

            items.append(
                CriticalBatchItem(
                    batch_id=b.batch_id,
                    batch_identifier=b.batch_identifier,
                    product_id=b.product_id,
                    product_name=b.product.name,
                    category=b.product.category,
                    current_quantity=b.current_quantity,
                    unit=b.product.default_unit,
                    expiry_date=b.expiry_date,
                    days_until_expiry=days_left,
                    status=status,
                )
            )

        return StockHealthResponse(
            store_id=store_id,
            total_critical_batches=len(items),
            expired_batches_count=expired_count,
            expiring_30_days_count=expiring_30_count,
            expiring_60_days_count=expiring_60_count,
            batches=items,
        )

    @staticmethod
    def get_sales_velocity(
        db: Session,
        store_id: uuid.UUID,
        period_days: int = 7,
        top_n: int = 5,
    ) -> SalesVelocityResponse:
        store = db.query(Store).filter(Store.store_id == store_id).first()
        if not store:
            raise EntityNotFoundException("Store", store_id)

        start_date = datetime.now(timezone.utc) - timedelta(days=period_days)

        # Top selling products
        top_results = (
            db.query(
                TransactionItem.product_id,
                TransactionItem.product_name,
                TransactionItem.category,
                TransactionItem.unit,
                func.sum(TransactionItem.quantity).label("total_sold"),
                func.sum(TransactionItem.line_total).label("total_revenue"),
            )
            .join(Transaction, TransactionItem.transaction_id == Transaction.transaction_id)
            .filter(
                Transaction.store_id == store_id,
                Transaction.payment_status == PaymentStatus.PAID.value,
                Transaction.created_at >= start_date,
            )
            .group_by(
                TransactionItem.product_id,
                TransactionItem.product_name,
                TransactionItem.category,
                TransactionItem.unit,
            )
            .order_by(desc("total_sold"))
            .limit(top_n)
            .all()
        )

        top_items = [
            TopSellingProductItem(
                product_id=r.product_id,
                product_name=r.product_name,
                category=r.category,
                unit=r.unit,
                total_quantity_sold=Decimal(str(r.total_sold or 0)),
                total_revenue=Decimal(str(r.total_revenue or 0)),
            )
            for r in top_results
        ]

        # Daily revenue trend
        daily_trends: list[DailyRevenueTrendItem] = []
        for d in range(period_days):
            day_target = (datetime.now(timezone.utc) - timedelta(days=period_days - 1 - d)).date()
            day_start = datetime(day_target.year, day_target.month, day_target.day, 0, 0, 0, tzinfo=timezone.utc)
            day_end = day_start + timedelta(days=1)

            day_stats = (
                db.query(
                    func.count(Transaction.transaction_id).label("tx_count"),
                    func.coalesce(func.sum(Transaction.final_total), Decimal("0.00")).label("rev"),
                )
                .filter(
                    Transaction.store_id == store_id,
                    Transaction.payment_status == PaymentStatus.PAID.value,
                    Transaction.created_at >= day_start,
                    Transaction.created_at < day_end,
                )
                .first()
            )

            daily_trends.append(
                DailyRevenueTrendItem(
                    date=day_target.isoformat(),
                    transaction_count=day_stats.tx_count if day_stats else 0,
                    revenue=Decimal(str(day_stats.rev or 0)) if day_stats else Decimal("0.00"),
                )
            )

        return SalesVelocityResponse(
            store_id=store_id,
            period_days=period_days,
            top_selling_items=top_items,
            daily_trend=daily_trends,
        )

    @staticmethod
    def get_inventory_status(db: Session, store_id: uuid.UUID) -> InventoryStatusResponse:
        store = db.query(Store).filter(Store.store_id == store_id).first()
        if not store:
            raise EntityNotFoundException("Store", store_id)

        products = (
            db.query(Product)
            .filter(
                Product.store_id == store_id,
                Product.is_active == True,
            )
            .all()
        )

        in_stock_count = 0
        low_stock_count = 0
        out_of_stock_count = 0
        low_stock_items: list[LowStockAlertItem] = []

        for p in products:
            curr_stock = sum((b.current_quantity for b in p.batches if b.current_quantity > 0), Decimal("0.000"))
            if curr_stock <= Decimal("0.000"):
                out_of_stock_count += 1
                low_stock_items.append(
                    LowStockAlertItem(
                        product_id=p.product_id,
                        product_name=p.name,
                        category=p.category,
                        unit=p.default_unit,
                        current_stock=curr_stock,
                        min_stock_alert_threshold=p.min_stock_alert_threshold,
                        selling_price=p.selling_price,
                    )
                )
            elif curr_stock <= p.min_stock_alert_threshold:
                low_stock_count += 1
                low_stock_items.append(
                    LowStockAlertItem(
                        product_id=p.product_id,
                        product_name=p.name,
                        category=p.category,
                        unit=p.default_unit,
                        current_stock=curr_stock,
                        min_stock_alert_threshold=p.min_stock_alert_threshold,
                        selling_price=p.selling_price,
                    )
                )
            else:
                in_stock_count += 1

        today_date = date.today()
        exp_summary = {
            "expired": db.query(Batch)
            .filter(
                Batch.store_id == store_id,
                Batch.current_quantity > 0,
                Batch.expiry_date < today_date,
            )
            .count(),
            "within_30_days": db.query(Batch)
            .filter(
                Batch.store_id == store_id,
                Batch.current_quantity > 0,
                Batch.expiry_date >= today_date,
                Batch.expiry_date <= today_date + timedelta(days=30),
            )
            .count(),
            "within_60_days": db.query(Batch)
            .filter(
                Batch.store_id == store_id,
                Batch.current_quantity > 0,
                Batch.expiry_date > today_date + timedelta(days=30),
                Batch.expiry_date <= today_date + timedelta(days=60),
            )
            .count(),
        }

        return InventoryStatusResponse(
            store_id=store_id,
            total_products=len(products),
            in_stock_products_count=in_stock_count,
            low_stock_products_count=low_stock_count,
            out_of_stock_products_count=out_of_stock_count,
            low_stock_items=low_stock_items,
            expiring_batches_summary=exp_summary,
        )
