import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.dependencies import verify_user_store_access
from app.core.exceptions import (
    EntityNotFoundException,
    ForbiddenException,
    InsufficientStockException,
    ValidationException,
)
from app.models.inventory import Batch, Product
from app.models.stock_transfer import StockTransfer, StockTransferItem
from app.models.store import Store
from app.models.user import User
from app.schemas.stock_transfer import (
    StockTransferCreate,
    StockTransferItemResponse,
    StockTransferResponse,
)


class StockTransferService:
    @classmethod
    def generate_transfer_number(cls, db: Session) -> str:
        count = db.query(func.count(StockTransfer.transfer_id)).scalar() or 0
        seq = count + 1
        transfer_number = f"TRF-{seq:05d}"
        while db.query(StockTransfer).filter(StockTransfer.transfer_number == transfer_number).first():
            seq += 1
            transfer_number = f"TRF-{seq:05d}"
        return transfer_number

    @classmethod
    def create_transfer(
        cls,
        db: Session,
        current_user: User,
        transfer_in: StockTransferCreate,
    ) -> StockTransfer:
        source_store_id = transfer_in.source_store_id
        dest_store_id = transfer_in.destination_store_id

        if source_store_id == dest_store_id:
            raise ValidationException("Source store and destination store cannot be the same store.")

        # Resolve Source Store
        source_store = db.query(Store).filter(Store.store_id == source_store_id, Store.is_active == True).first()
        if not source_store:
            raise EntityNotFoundException("Source Store", source_store_id)

        # Resolve Destination Store
        dest_store = db.query(Store).filter(Store.store_id == dest_store_id, Store.is_active == True).first()
        if not dest_store:
            raise EntityNotFoundException("Destination Store", dest_store_id)

        # Enforce Admin or Connected Operator Authorization
        # User must be an Admin or have authorized access to both stores
        is_admin_user = current_user.is_admin()
        has_source = is_admin_user or verify_user_store_access(db, current_user, source_store_id)
        has_dest = is_admin_user or verify_user_store_access(db, current_user, dest_store_id)

        if not has_source or not has_dest:
            raise ForbiddenException("Only administrators or operators connected to both stores can perform stock transfers.")

        if not transfer_in.items:
            raise ValidationException("At least one product item is required for stock transfer.")

        # -------------------------------------------------------------
        # 1. PRE-VALIDATION: Check all source products & stocks atomically
        # -------------------------------------------------------------
        prepared_operations: list[dict] = []
        total_transfer_quantity = Decimal("0.000")

        for item_in in transfer_in.items:
            transfer_qty = Decimal(str(item_in.quantity))
            if transfer_qty <= Decimal("0.000"):
                raise ValidationException("Transfer quantity must be strictly greater than zero.")

            source_product = (
                db.query(Product)
                .filter(
                    Product.product_id == item_in.product_id,
                    Product.store_id == source_store_id,
                )
                .first()
            )
            if not source_product:
                raise EntityNotFoundException("Product in source store", item_in.product_id)

            if not source_product.is_active:
                raise ValidationException(f"Product '{source_product.name}' is inactive and cannot be transferred.")

            # Retrieve positive batches for FEFO stock deduction
            source_batches = (
                db.query(Batch)
                .filter(
                    Batch.product_id == source_product.product_id,
                    Batch.store_id == source_store_id,
                    Batch.current_quantity > Decimal("0.000"),
                )
                .order_by(Batch.expiry_date.asc(), Batch.purchase_date.asc(), Batch.created_at.asc())
                .all()
            )

            total_available = sum((b.current_quantity for b in source_batches), Decimal("0.000"))
            if total_available < transfer_qty:
                raise InsufficientStockException(
                    product_name=source_product.name,
                    product_id=source_product.product_id,
                    requested=float(transfer_qty),
                    available=float(total_available),
                )

            total_transfer_quantity += transfer_qty
            prepared_operations.append({
                "source_product": source_product,
                "transfer_qty": transfer_qty,
                "source_batches": source_batches,
            })

        # -------------------------------------------------------------
        # 2. ATOMIC EXECUTION: Deduct from Source, Inward to Destination
        # -------------------------------------------------------------
        transfer_number = cls.generate_transfer_number(db)
        transfer = StockTransfer(
            transfer_id=uuid.uuid4(),
            transfer_number=transfer_number,
            source_store_id=source_store_id,
            destination_store_id=dest_store_id,
            created_by_user_id=current_user.user_id,
            transferred_by_name=current_user.name,
            status="COMPLETED",
            notes=transfer_in.notes,
            total_items=len(prepared_operations),
            total_quantity=total_transfer_quantity,
        )
        db.add(transfer)
        db.flush()

        for op in prepared_operations:
            source_product: Product = op["source_product"]
            transfer_qty: Decimal = op["transfer_qty"]
            source_batches: list[Batch] = op["source_batches"]

            # Deduct from source batches using FEFO
            remaining_to_deduct = transfer_qty
            deducted_portions: list[dict] = []

            for batch in source_batches:
                if remaining_to_deduct <= Decimal("0.000"):
                    break
                deduct_qty = min(batch.current_quantity, remaining_to_deduct)
                batch.current_quantity = (batch.current_quantity - deduct_qty).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
                remaining_to_deduct = (remaining_to_deduct - deduct_qty).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)

                deducted_portions.append({
                    "batch_identifier": batch.batch_identifier,
                    "quantity": deduct_qty,
                    "purchase_price": batch.purchase_price,
                    "expiry_date": batch.expiry_date,
                    "purchase_date": batch.purchase_date,
                })

            # Check if matching product already exists in Destination Store
            dest_product = None
            if source_product.barcode and source_product.barcode.strip():
                dest_product = (
                    db.query(Product)
                    .filter(
                        Product.store_id == dest_store_id,
                        Product.barcode == source_product.barcode.strip(),
                    )
                    .first()
                )

            if not dest_product:
                dest_product = (
                    db.query(Product)
                    .filter(
                        Product.store_id == dest_store_id,
                        func.lower(Product.name) == func.lower(source_product.name.strip()),
                    )
                    .first()
                )

            auto_created_product = False
            if dest_product:
                # If product already exists in destination, reactivate if it was inactive
                if not dest_product.is_active:
                    dest_product.is_active = True
            else:
                # On-the-go creation of missing product in destination store
                auto_created_product = True
                dest_product = Product(
                    product_id=uuid.uuid4(),
                    store_id=dest_store_id,
                    name=source_product.name,
                    description=source_product.description,
                    category=source_product.category or "General",
                    default_unit=source_product.default_unit,
                    selling_price=source_product.selling_price,
                    cost_price=source_product.cost_price,
                    min_stock_alert_threshold=source_product.min_stock_alert_threshold,
                    barcode=source_product.barcode,
                    is_active=True,
                )
                db.add(dest_product)
                db.flush()

            # Create Inward Batches in Destination Store
            for portion in deducted_portions:
                batch_id_str = portion["batch_identifier"]
                if not batch_id_str.startswith("TRF-"):
                    batch_id_str = f"TRF-{batch_id_str}"

                remaining_dest_qty = Decimal(str(portion["quantity"])).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
                dest_neg_batches = (
                    db.query(Batch)
                    .filter(
                        Batch.product_id == dest_product.product_id,
                        Batch.store_id == dest_store_id,
                        Batch.current_quantity < Decimal("0.000"),
                    )
                    .order_by(Batch.created_at.asc())
                    .all()
                )
                for neg_b in dest_neg_batches:
                    if remaining_dest_qty <= Decimal("0.000"):
                        break
                    deficit = abs(neg_b.current_quantity)
                    covered = min(remaining_dest_qty, deficit)
                    neg_b.current_quantity = (neg_b.current_quantity + covered).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
                    remaining_dest_qty = (remaining_dest_qty - covered).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)

                dest_batch = Batch(
                    batch_id=uuid.uuid4(),
                    product_id=dest_product.product_id,
                    store_id=dest_store_id,
                    batch_identifier=batch_id_str,
                    initial_quantity=portion["quantity"],
                    current_quantity=remaining_dest_qty,
                    purchase_price=portion["purchase_price"],
                    expiry_date=portion["expiry_date"],
                    purchase_date=date.today(),
                )
                db.add(dest_batch)

            # Record Transfer Item
            transfer_item = StockTransferItem(
                item_id=uuid.uuid4(),
                transfer_id=transfer.transfer_id,
                source_product_id=source_product.product_id,
                destination_product_id=dest_product.product_id,
                product_name=source_product.name,
                category=source_product.category,
                unit=source_product.default_unit,
                quantity=transfer_qty,
                auto_created_product=auto_created_product,
            )
            db.add(transfer_item)

        db.commit()
        db.refresh(transfer)
        return transfer

    @classmethod
    def list_transfers(
        cls,
        db: Session,
        current_user: User,
        store_id: uuid.UUID | None = None,
        direction: str = "all",
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[StockTransfer]:
        query = db.query(StockTransfer)

        if store_id:
            if not current_user.is_admin():
                accessible_ids = [s.store_id for s in current_user.accessible_stores]
                if store_id not in accessible_ids:
                    return []

            if direction == "outward":
                query = query.filter(StockTransfer.source_store_id == store_id)
            elif direction == "inward":
                query = query.filter(StockTransfer.destination_store_id == store_id)
            else:
                query = query.filter(
                    or_(
                        StockTransfer.source_store_id == store_id,
                        StockTransfer.destination_store_id == store_id,
                    )
                )
        elif not current_user.is_admin():
            # If user is not global admin, only show transfers for stores they have access to
            accessible_ids = [s.store_id for s in current_user.accessible_stores]
            if not accessible_ids:
                return []
            query = query.filter(
                or_(
                    StockTransfer.source_store_id.in_(accessible_ids),
                    StockTransfer.destination_store_id.in_(accessible_ids),
                )
            )

        if search and search.strip():
            term = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    StockTransfer.transfer_number.ilike(term),
                    StockTransfer.notes.ilike(term),
                    StockTransfer.transferred_by_name.ilike(term),
                    StockTransfer.items.any(StockTransferItem.product_name.ilike(term)),
                )
            )

        return query.order_by(StockTransfer.created_at.desc()).offset(offset).limit(limit).all()

    @classmethod
    def get_transfer(
        cls,
        db: Session,
        current_user: User,
        transfer_id: uuid.UUID,
    ) -> StockTransfer:
        transfer = db.query(StockTransfer).filter(StockTransfer.transfer_id == transfer_id).first()
        if not transfer:
            raise EntityNotFoundException("StockTransfer", transfer_id)

        if not current_user.is_admin():
            accessible_ids = [s.store_id for s in current_user.accessible_stores]
            if transfer.source_store_id not in accessible_ids and transfer.destination_store_id not in accessible_ids:
                raise ForbiddenException("You do not have access to view this stock transfer.")

        return transfer

    @classmethod
    def to_response(cls, transfer: StockTransfer) -> StockTransferResponse:
        items_responses = [
            StockTransferItemResponse(
                item_id=it.item_id,
                transfer_id=it.transfer_id,
                source_product_id=it.source_product_id,
                destination_product_id=it.destination_product_id,
                product_name=it.product_name,
                category=it.category,
                unit=it.unit,
                quantity=it.quantity,
                auto_created_product=it.auto_created_product,
            )
            for it in (transfer.items or [])
        ]

        source_name = transfer.source_store.name if transfer.source_store else "Unknown Store"
        dest_name = transfer.destination_store.name if transfer.destination_store else "Unknown Store"

        return StockTransferResponse(
            transfer_id=transfer.transfer_id,
            transfer_number=transfer.transfer_number,
            source_store_id=transfer.source_store_id,
            source_store_name=source_name,
            destination_store_id=transfer.destination_store_id,
            destination_store_name=dest_name,
            created_by_user_id=transfer.created_by_user_id,
            transferred_by_name=transfer.transferred_by_name,
            status=transfer.status,
            notes=transfer.notes,
            total_items=transfer.total_items,
            total_quantity=transfer.total_quantity,
            created_at=transfer.created_at,
            items=items_responses,
        )
