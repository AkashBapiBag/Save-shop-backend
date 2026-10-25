import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.exceptions import EntityNotFoundException
from app.models.inventory import Batch, Product
from app.models.store import Store
from app.schemas.inventory import (
    BatchReceiveBulk,
    BatchReceiveSingle,
    BatchResponse,
    ProductCreate,
    ProductResponse,
    ProductUpdate,
)


class InventoryService:
    @staticmethod
    def create_product(db: Session, store_id: uuid.UUID, product_in: ProductCreate) -> Product:
        store = db.query(Store).filter(Store.store_id == store_id).first()
        if not store:
            raise EntityNotFoundException("Store", store_id)

        product = Product(
            product_id=uuid.uuid4(),
            store_id=store_id,
            name=product_in.name,
            description=product_in.description,
            category=product_in.category,
            default_unit=product_in.default_unit.value,
            selling_price=product_in.selling_price,
            cost_price=product_in.cost_price,
            min_stock_alert_threshold=product_in.min_stock_alert_threshold,
            barcode=product_in.barcode,
            is_active=True,
        )
        db.add(product)
        db.commit()
        db.refresh(product)
        return product

    @staticmethod
    def get_product(db: Session, product_id: uuid.UUID, store_id: uuid.UUID | None = None) -> Product:
        query = db.query(Product).filter(Product.product_id == product_id)
        if store_id:
            query = query.filter(Product.store_id == store_id)
        product = query.first()
        if not product:
            raise EntityNotFoundException("Product", product_id)
        return product

    @staticmethod
    def update_product(
        db: Session,
        product_id: uuid.UUID,
        product_in: ProductUpdate,
        store_id: uuid.UUID | None = None,
    ) -> Product:
        product = InventoryService.get_product(db, product_id, store_id)

        if product_in.name is not None:
            product.name = product_in.name
        if product_in.description is not None:
            product.description = product_in.description
        if product_in.category is not None:
            product.category = product_in.category
        if product_in.default_unit is not None:
            product.default_unit = product_in.default_unit.value
        if product_in.selling_price is not None:
            product.selling_price = product_in.selling_price
        if product_in.cost_price is not None:
            product.cost_price = product_in.cost_price
        if product_in.min_stock_alert_threshold is not None:
            product.min_stock_alert_threshold = product_in.min_stock_alert_threshold
        if product_in.barcode is not None:
            product.barcode = product_in.barcode
        if product_in.is_active is not None:
            product.is_active = product_in.is_active

        db.commit()
        db.refresh(product)
        return product

    @staticmethod
    def list_products(
        db: Session,
        store_id: uuid.UUID,
        category: str | None = None,
        search: str | None = None,
        active_only: bool = True,
    ) -> list[tuple[Product, Decimal]]:
        """
        Returns list of tuples: (Product, computed_total_stock)
        where total_stock = sum(current_quantity) of all positive batches.
        """
        stock_subquery = (
            db.query(
                Batch.product_id,
                func.coalesce(func.sum(Batch.current_quantity), Decimal("0.000")).label("total_stock"),
            )
            .filter(Batch.store_id == store_id, Batch.current_quantity > 0)
            .group_by(Batch.product_id)
            .subquery()
        )

        query = (
            db.query(
                Product,
                func.coalesce(stock_subquery.c.total_stock, Decimal("0.000")).label("stock"),
            )
            .outerjoin(stock_subquery, Product.product_id == stock_subquery.c.product_id)
            .filter(Product.store_id == store_id)
        )

        if active_only:
            query = query.filter(Product.is_active == True)
        if category:
            query = query.filter(Product.category.ilike(f"%{category}%"))
        if search:
            query = query.filter((Product.name.ilike(f"%{search}%")) | (Product.barcode == search))

        return query.order_by(Product.name.asc()).all()

    @staticmethod
    def list_categories(db: Session, store_id: uuid.UUID) -> list[dict]:
        """
        Returns all unique categories used in the active store tenant with product counts.
        Guarantees strict tenant isolation: Store A will never see Store B's categories.
        """
        results = (
            db.query(
                Product.category,
                func.count(Product.product_id).label("count"),
            )
            .filter(Product.store_id == store_id, Product.is_active == True)
            .group_by(Product.category)
            .order_by(Product.category.asc())
            .all()
        )
        return [{"name": r[0], "count": int(r[1])} for r in results]

    @staticmethod
    def receive_single_batch(
        db: Session,
        store_id: uuid.UUID,
        receive_in: BatchReceiveSingle,
    ) -> Batch:
        """
        Atomic operation 1: Single batch stock acquisition.
        """
        product = (
            db.query(Product)
            .filter(
                Product.product_id == receive_in.product_id,
                Product.store_id == store_id,
            )
            .first()
        )
        if not product:
            raise EntityNotFoundException("Product in store", receive_in.product_id)

        new_batch = Batch(
            batch_id=uuid.uuid4(),
            product_id=receive_in.product_id,
            store_id=store_id,
            batch_identifier=receive_in.batch_identifier,
            initial_quantity=receive_in.quantity,
            current_quantity=receive_in.quantity,  # Source of truth
            purchase_price=receive_in.purchase_price,
            purchase_date=receive_in.purchase_date,
            expiry_date=receive_in.expiry_date,
        )
        db.add(new_batch)
        db.commit()
        db.refresh(new_batch)
        return new_batch

    @staticmethod
    def receive_bulk_batches(
        db: Session,
        store_id: uuid.UUID,
        bulk_in: BatchReceiveBulk,
    ) -> list[Batch]:
        """
        Atomic operation 2: Bulk receiving of multiple batches across products.
        Enforces transaction atomicity: either all batches succeed or none are committed.
        """
        store = db.query(Store).filter(Store.store_id == store_id).first()
        if not store:
            raise EntityNotFoundException("Store", store_id)

        created_batches: list[Batch] = []

        try:
            for item in bulk_in.batches:
                product = (
                    db.query(Product)
                    .filter(
                        Product.product_id == item.product_id,
                        Product.store_id == store_id,
                    )
                    .first()
                )
                if not product:
                    raise EntityNotFoundException(f"Product {item.product_id} in store", store_id)

                batch = Batch(
                    batch_id=uuid.uuid4(),
                    product_id=item.product_id,
                    store_id=store_id,
                    batch_identifier=item.batch_identifier,
                    initial_quantity=item.quantity,
                    current_quantity=item.quantity,
                    purchase_price=item.purchase_price or product.cost_price,
                    purchase_date=item.purchase_date,
                    expiry_date=item.expiry_date,
                )
                db.add(batch)
                created_batches.append(batch)

            db.commit()
            for b in created_batches:
                db.refresh(b)
            return created_batches
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def list_batches(
        db: Session,
        store_id: uuid.UUID,
        product_id: uuid.UUID | None = None,
        only_active_stock: bool = False,
    ) -> list[Batch]:
        query = db.query(Batch).filter(Batch.store_id == store_id)
        if product_id:
            # Strictly verify that target product belongs to active store tenant
            prod = (
                db.query(Product)
                .filter(
                    Product.product_id == product_id,
                    Product.store_id == store_id,
                )
                .first()
            )
            if not prod:
                return []
            query = query.filter(Batch.product_id == product_id)
        if only_active_stock:
            query = query.filter(Batch.current_quantity > 0)
        return query.order_by(Batch.expiry_date.asc(), Batch.purchase_date.asc()).all()

    @staticmethod
    def to_batch_response(batch: Batch) -> BatchResponse:
        today = date.today()
        days_diff = (batch.expiry_date - today).days
        return BatchResponse(
            batch_id=batch.batch_id,
            product_id=batch.product_id,
            store_id=batch.store_id,
            batch_identifier=batch.batch_identifier,
            initial_quantity=batch.initial_quantity,
            current_quantity=batch.current_quantity,
            purchase_price=batch.purchase_price,
            expiry_date=batch.expiry_date,
            purchase_date=batch.purchase_date,
            days_to_expiry=days_diff,
            is_expired=batch.expiry_date < today,
            created_at=batch.created_at,
        )

    @staticmethod
    def to_product_response(product: Product, total_stock: Decimal | None = None) -> ProductResponse:
        if total_stock is None:
            total_stock = sum(
                (b.current_quantity for b in product.batches if b.current_quantity > 0),
                Decimal("0.000"),
            )
        batch_responses = [InventoryService.to_batch_response(b) for b in product.batches]
        return ProductResponse(
            product_id=product.product_id,
            store_id=product.store_id,
            name=product.name,
            description=product.description,
            category=product.category,
            default_unit=product.default_unit,
            selling_price=product.selling_price,
            cost_price=product.cost_price,
            min_stock_alert_threshold=product.min_stock_alert_threshold,
            barcode=product.barcode,
            total_current_stock=total_stock,
            is_active=product.is_active,
            created_at=product.created_at,
            updated_at=product.updated_at,
            batches=batch_responses,
        )
