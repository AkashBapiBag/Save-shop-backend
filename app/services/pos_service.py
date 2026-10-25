import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.exceptions import (
    EntityNotFoundException,
    InsufficientStockException,
    ValidationException,
)
from app.models.inventory import Batch, Product
from app.models.store import Store
from app.models.transaction import (
    PaymentMethod,
    PaymentStatus,
    Transaction,
    TransactionBatchAllocation,
    TransactionItem,
)
from app.models.user import User
from app.schemas.billing import (
    BatchAllocationResponse,
    OfflineSyncRequest,
    OfflineSyncResponse,
    OfflineSyncTransactionResult,
    POSTransactionCreate,
    ReceiptResponse,
    StockValidationItem,
    StockValidationItemError,
    StockValidationResponse,
    StoreReceiptHeader,
    TransactionItemResponse,
    TransactionResponse,
)
from app.services.notification_service import NotificationService
from app.services.store_service import StoreService
from app.utils.number_to_words import number_to_words_inr
from app.utils.unit_calc import UnitCalculator

TWO_PLACES = Decimal("0.01")
THREE_PLACES = Decimal("0.001")


def quantize_currency(amount: Decimal) -> Decimal:
    return amount.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def quantize_quantity(qty: Decimal) -> Decimal:
    return qty.quantize(THREE_PLACES, rounding=ROUND_HALF_UP)


class POSService:
    @classmethod
    def get_next_invoice_sequence(cls, db: Session, store_id: uuid.UUID) -> int:
        """
        Determines the next incremental invoice sequence for the given store.
        Guarantees strict consecutive numbering (1, 2, 3, 4...).
        """
        max_seq = db.query(func.max(Transaction.invoice_seq)).filter(Transaction.store_id == store_id).scalar()
        if max_seq is not None and max_seq > 0:
            return int(max_seq) + 1

        count = db.query(func.count(Transaction.transaction_id)).filter(Transaction.store_id == store_id).scalar()
        return (count or 0) + 1

    @classmethod
    def generate_invoice_number(cls, db: Session, store_id: uuid.UUID) -> tuple[int, str]:
        """
        Generates a strictly unique, human-readable, consecutive invoice number.
        Format: INV-00001, INV-00002, ...
        Returns (seq_number, invoice_number_str).
        """
        next_seq = cls.get_next_invoice_sequence(db, store_id)
        invoice_number = f"INV-{next_seq:05d}"
        return next_seq, invoice_number

    @classmethod
    def process_pos_transaction(
        cls,
        db: Session,
        store_id: uuid.UUID,
        cashier: User,
        pos_in: POSTransactionCreate,
        offline_sync: bool = False,
        auto_commit: bool = True,
    ) -> Transaction:
        """
        Executes the POS Transaction Flow atomically:
        1. Input validation & Store resolution.
        2. Base price calculation (Quantity * UnitPrice).
        3. Priority Discount Application:
           - Item Level (% discount on item)
           - Category Level (% discount on category)
           - Total Level (% discount on subtotal)
        4. FEFO (First-Expiry, First-Out) Inventory Deduction with strict validation.
        5. Atomic persistence & Notification triggers.
        """
        store = db.query(Store).filter(Store.store_id == store_id).first()
        if not store:
            raise EntityNotFoundException("Store", store_id)

        # Idempotency check for offline transactions (scoped to active store tenant)
        if pos_in.client_offline_id:
            existing = (
                db.query(Transaction)
                .filter(
                    Transaction.store_id == store_id,
                    Transaction.client_offline_id == pos_in.client_offline_id,
                )
                .first()
            )
            if existing:
                return existing

        # Map optional category discounts for fast lookup: category_name.lower() -> discount_pct
        cat_discount_map: dict[str, Decimal] = {}
        if pos_in.category_discounts:
            for cd in pos_in.category_discounts:
                cat_discount_map[cd.category.strip().lower()] = Decimal(str(cd.discount_pct))

        total_discount_pct = Decimal(str(pos_in.total_discount_pct or 0))
        total_discount_amount_input = Decimal(str(pos_in.total_discount_amount or 0))
        discount_type = (pos_in.discount_type or "percentage").lower()

        # Financial accumulators
        accumulated_subtotal = Decimal("0.00")  # Sum of base line totals
        accumulated_item_discount = Decimal("0.00")  # Sum of item level discounts
        accumulated_cat_discount = Decimal("0.00")  # Sum of category level discounts
        accumulated_intermediate_subtotal = Decimal("0.00")  # Sum of lines after item & cat discounts
        accumulated_cashback = Decimal("0.00")  # Sum of product-level cashbacks

        prepared_items: list[dict] = []
        low_stock_alerts_to_send: list[tuple[Product, Decimal]] = []

        # -------------------------------------------------------------
        # STEP 1 & 2 & 3: Price Calculation, Line Cashback & Base Totals
        # -------------------------------------------------------------
        for item_in in pos_in.items:
            product = (
                db.query(Product)
                .filter(
                    Product.product_id == item_in.product_id,
                    Product.store_id == store_id,
                )
                .first()
            )
            if not product:
                raise EntityNotFoundException("Product in store", item_in.product_id)

            if not product.is_active:
                raise ValidationException(f"Product '{product.name}' is currently inactive and cannot be sold.")

            qty = Decimal(str(item_in.quantity))
            product_unit = product.default_unit
            requested_unit = item_in.unit.value if getattr(item_in, "unit", None) else product_unit

            if not UnitCalculator.is_compatible(requested_unit, product_unit):
                raise ValidationException(
                    f"Requested unit '{requested_unit}' is incompatible with product unit '{product_unit}' for '{product.name}'."
                )

            deduction_qty = UnitCalculator.convert_quantity(
                quantity=qty,
                from_unit=requested_unit,
                to_unit=product_unit,
            )

            # 1. Base item total & unit price determination
            if item_in.unit_price_override is not None:
                unit_price = Decimal(str(item_in.unit_price_override))
                line_base = quantize_currency(qty * unit_price)
            else:
                base_product_price = Decimal(str(product.selling_price))
                line_base = quantize_currency(deduction_qty * base_product_price)
                unit_price = quantize_currency(line_base / qty) if qty > Decimal("0.000") else base_product_price

            # 2. Product-level Cashback (Amount or Percentage)
            cashback_amt = Decimal("0.00")
            cashback_pct = Decimal("0.00")
            if item_in.cashback_pct and item_in.cashback_pct > Decimal("0.00"):
                cashback_pct = min(Decimal("100.00"), max(Decimal("0.00"), Decimal(str(item_in.cashback_pct))))
                cashback_amt = quantize_currency(line_base * (cashback_pct / Decimal("100")))
            elif item_in.cashback_amount and item_in.cashback_amount > Decimal("0.00"):
                cashback_amt = min(line_base, max(Decimal("0.00"), Decimal(str(item_in.cashback_amount))))
                cashback_pct = (
                    quantize_currency(cashback_amt / line_base * Decimal("100")) if line_base > Decimal("0.00") else Decimal("0.00")
                )

            # 3. Item-level and Category-level discounts (if provided)
            item_disc_pct = Decimal(str(item_in.item_discount_pct or 0))
            item_disc_amt = quantize_currency(line_base * (item_disc_pct / Decimal("100")))
            price_after_item_disc = max(Decimal("0.00"), line_base - item_disc_amt)

            category_key = (product.category or "General").strip().lower()
            cat_disc_pct = (
                Decimal(str(item_in.category_discount_pct))
                if item_in.category_discount_pct and item_in.category_discount_pct > 0
                else cat_discount_map.get(category_key, Decimal("0.00"))
            )
            cat_disc_amt = quantize_currency(price_after_item_disc * (cat_disc_pct / Decimal("100")))
            line_intermediate = max(Decimal("0.00"), price_after_item_disc - cat_disc_amt)

            accumulated_subtotal += line_base
            accumulated_item_discount += item_disc_amt
            accumulated_cat_discount += cat_disc_amt
            accumulated_intermediate_subtotal += line_intermediate
            accumulated_cashback += cashback_amt

            prepared_items.append(
                {
                    "product": product,
                    "quantity": qty,
                    "requested_unit": requested_unit,
                    "deduction_qty": deduction_qty,
                    "unit_price": unit_price,
                    "item_disc_pct": item_disc_pct,
                    "item_disc_amt": item_disc_amt,
                    "cat_disc_pct": cat_disc_pct,
                    "cat_disc_amt": cat_disc_amt,
                    "cashback_amt": cashback_amt,
                    "cashback_pct": cashback_pct,
                    "line_base": line_base,
                    "line_intermediate": line_intermediate,
                }
            )

        # -------------------------------------------------------------
        # STEP 4: Subtotal Level Discount & Proportional Distribution
        # -------------------------------------------------------------
        if discount_type == "amount" or (total_discount_amount_input > Decimal("0.00") and total_discount_pct == Decimal("0.00")):
            total_subtotal_discount = min(accumulated_intermediate_subtotal, max(Decimal("0.00"), total_discount_amount_input))
            total_discount_pct = (
                quantize_currency(total_subtotal_discount / accumulated_intermediate_subtotal * Decimal("100"))
                if accumulated_intermediate_subtotal > Decimal("0.00")
                else Decimal("0.00")
            )
        else:
            total_discount_pct = min(Decimal("100.00"), max(Decimal("0.00"), total_discount_pct))
            total_subtotal_discount = quantize_currency(accumulated_intermediate_subtotal * (total_discount_pct / Decimal("100")))

        final_total = max(Decimal("0.00"), accumulated_intermediate_subtotal - total_subtotal_discount)

        # Distribute subtotal discount proportionally to each item for tax invoice line items
        allocated_sub_disc = Decimal("0.00")
        num_items = len(prepared_items)
        for i, item_data in enumerate(prepared_items):
            line_base = item_data["line_base"]
            if i == num_items - 1:
                item_sub_disc = total_subtotal_discount - allocated_sub_disc
            else:
                if accumulated_intermediate_subtotal > Decimal("0.00"):
                    ratio = item_data["line_intermediate"] / accumulated_intermediate_subtotal
                    item_sub_disc = quantize_currency(total_subtotal_discount * ratio)
                else:
                    item_sub_disc = Decimal("0.00")
                allocated_sub_disc += item_sub_disc

            total_line_disc = quantize_currency(item_data["item_disc_amt"] + item_data["cat_disc_amt"] + item_sub_disc)
            item_data["line_discount"] = total_line_disc
            item_data["line_total"] = max(Decimal("0.00"), line_base - total_line_disc)
            item_data["effective_discount_pct"] = (
                quantize_currency(total_line_disc / line_base * Decimal("100")) if line_base > Decimal("0.00") else Decimal("0.00")
            )

        # -------------------------------------------------------------
        # STEP 5: Inventory FEFO (First-Expiry, First-Out) Deduction
        # -------------------------------------------------------------
        transaction_items_to_save: list[TransactionItem] = []

        for item_data in prepared_items:
            product: Product = item_data["product"]
            req_qty = item_data["deduction_qty"]
            disp_qty = item_data["quantity"]
            disp_unit = item_data["requested_unit"]

            # Query all positive batches for this product in this store
            # Strictly ordered by expiry_date ASC (FEFO), then purchase_date ASC
            batches = (
                db.query(Batch)
                .filter(
                    Batch.product_id == product.product_id,
                    Batch.store_id == store_id,
                    Batch.current_quantity > 0,
                )
                .order_by(Batch.expiry_date.asc(), Batch.purchase_date.asc(), Batch.created_at.asc())
                .all()
            )

            total_available = sum((b.current_quantity for b in batches), Decimal("0.000"))
            if total_available < req_qty:
                raise InsufficientStockException(
                    product_name=product.name,
                    product_id=product.product_id,
                    requested=float(req_qty),
                    available=float(total_available),
                )

            # Prepare TransactionItem record
            tx_item = TransactionItem(
                item_id=uuid.uuid4(),
                product_id=product.product_id,
                product_name=product.name,
                category=product.category,
                unit=disp_unit,
                quantity=disp_qty,
                unit_price=item_data["unit_price"],
                item_discount_pct=item_data["item_disc_pct"],
                category_discount_pct=item_data["cat_disc_pct"],
                cashback_amount=item_data["cashback_amt"],
                cashback_pct=item_data["cashback_pct"],
                discount_amount=item_data["line_discount"],
                discount_pct=item_data["effective_discount_pct"],
                line_base_total=item_data["line_base"],
                line_discount_amount=item_data["line_discount"],
                line_total=item_data["line_total"],
            )

            # Deduct in FEFO order across batches
            remaining_to_deduct = req_qty
            for batch in batches:
                if remaining_to_deduct <= Decimal("0.000"):
                    break

                deduct_amount = min(batch.current_quantity, remaining_to_deduct)
                batch.current_quantity = quantize_quantity(batch.current_quantity - deduct_amount)
                remaining_to_deduct = quantize_quantity(remaining_to_deduct - deduct_amount)

                # Record batch allocation
                allocation = TransactionBatchAllocation(
                    allocation_id=uuid.uuid4(),
                    transaction_item_id=tx_item.item_id,
                    batch_id=batch.batch_id,
                    product_id=product.product_id,
                    quantity_deducted=deduct_amount,
                    batch_identifier=batch.batch_identifier,
                    expiry_date=batch.expiry_date,
                )
                tx_item.allocations.append(allocation)

            # Check if remaining stock for this product triggers low stock alert
            remaining_total_stock = total_available - req_qty
            if remaining_total_stock <= product.min_stock_alert_threshold:
                low_stock_alerts_to_send.append((product, remaining_total_stock))

            transaction_items_to_save.append(tx_item)

        # -------------------------------------------------------------
        # STEP 6: Create and Save Transaction Record
        # -------------------------------------------------------------
        # Determine received amount and balance
        if pos_in.received_amount is not None:
            received_amt = quantize_currency(Decimal(str(pos_in.received_amount)))
        elif pos_in.payment_method == PaymentMethod.CREDIT:
            received_amt = Decimal("0.00")
        else:
            received_amt = final_total

        balance_amt = max(Decimal("0.00"), quantize_currency(final_total - received_amt))
        payment_status_val = (
            PaymentStatus.PENDING.value
            if (pos_in.payment_method == PaymentMethod.CREDIT or balance_amt > Decimal("0.00"))
            else PaymentStatus.PAID.value
        )

        invoice_seq, invoice_number = cls.generate_invoice_number(db, store_id)
        transaction = Transaction(
            transaction_id=uuid.uuid4(),
            store_id=store_id,
            invoice_seq=invoice_seq,
            invoice_number=invoice_number,
            cashier_id=cashier.user_id if cashier else None,
            customer_name=pos_in.customer_name,
            customer_phone=pos_in.customer_phone,
            customer_email=pos_in.customer_email,
            subtotal=accumulated_subtotal,
            item_discount_amount=accumulated_item_discount,
            category_discount_amount=accumulated_cat_discount,
            total_discount_percentage=total_discount_pct,
            total_discount_amount=total_subtotal_discount,
            total_cashback_amount=accumulated_cashback,
            tax_amount=Decimal("0.00"),
            final_total=final_total,
            received_amount=received_amt,
            balance_amount=balance_amt,
            payment_method=pos_in.payment_method.value,
            payment_status=payment_status_val,
            notes=pos_in.notes,
            offline_synced=offline_sync,
            client_offline_id=pos_in.client_offline_id,
            items=transaction_items_to_save,
        )

        db.add(transaction)

        # Dispatch async notification logs
        for prod, rem_stock in low_stock_alerts_to_send:
            NotificationService.trigger_low_stock_alert(db, store_id, prod, float(rem_stock))

        NotificationService.trigger_payment_confirmation(db, transaction)

        # Atomic persistence
        if auto_commit:
            db.commit()
            db.refresh(transaction)
        else:
            db.flush()
        return transaction

    @classmethod
    def validate_cart_stock(cls, db: Session, store_id: uuid.UUID, items: list[StockValidationItem]) -> StockValidationResponse:
        """
        Validates inventory stock for a set of items in real-time before proceeding to checkout.
        """
        errors: list[StockValidationItemError] = []
        for it in items:
            product = (
                db.query(Product)
                .filter(
                    Product.product_id == it.product_id,
                    Product.store_id == store_id,
                )
                .first()
            )
            if not product:
                errors.append(
                    StockValidationItemError(
                        product_id=it.product_id,
                        product_name="Unknown Product",
                        available_stock=Decimal("0.000"),
                        requested_stock=it.quantity,
                        message="Product not found in this store",
                    )
                )
                continue

            product_unit = product.default_unit
            req_unit = it.unit.value if getattr(it, "unit", None) else product_unit
            if not UnitCalculator.is_compatible(req_unit, product_unit):
                errors.append(
                    StockValidationItemError(
                        product_id=product.product_id,
                        product_name=product.name,
                        available_stock=Decimal("0.000"),
                        requested_stock=it.quantity,
                        message=f"Unit '{req_unit}' is incompatible with product unit '{product_unit}'",
                    )
                )
                continue

            deduction_qty = UnitCalculator.convert_quantity(it.quantity, req_unit, product_unit)

            batches = (
                db.query(Batch)
                .filter(
                    Batch.product_id == product.product_id,
                    Batch.store_id == store_id,
                    Batch.current_quantity > 0,
                )
                .all()
            )
            available = sum((b.current_quantity for b in batches), Decimal("0.000"))
            if available < deduction_qty:
                errors.append(
                    StockValidationItemError(
                        product_id=product.product_id,
                        product_name=product.name,
                        available_stock=available,
                        requested_stock=it.quantity,
                        message=f"Only {available} {product.default_unit} available in stock (requested {it.quantity} {req_unit})",
                    )
                )

        return StockValidationResponse(is_valid=len(errors) == 0, errors=errors)

    @classmethod
    def sync_offline_transactions(
        cls,
        db: Session,
        store_id: uuid.UUID,
        cashier: User,
        sync_req: OfflineSyncRequest,
    ) -> OfflineSyncResponse:
        """
        Synchronizes a batch of offline captured transactions.
        Idempotent on client_offline_id per store tenant.
        Uses database savepoints so individual transaction failures do not abort successful ones.
        """
        results: list[OfflineSyncTransactionResult] = []
        synced_count = 0
        already_synced_count = 0
        failed_count = 0

        target_store_id = sync_req.store_id or store_id

        for tx_in in sync_req.transactions:
            client_offline_id = tx_in.client_offline_id
            savepoint = db.begin_nested()
            try:
                # Idempotency verification
                if client_offline_id:
                    existing = (
                        db.query(Transaction)
                        .filter(
                            Transaction.store_id == target_store_id,
                            Transaction.client_offline_id == client_offline_id,
                        )
                        .first()
                    )
                    if existing:
                        already_synced_count += 1
                        results.append(
                            OfflineSyncTransactionResult(
                                client_offline_id=client_offline_id,
                                invoice_number=existing.invoice_number,
                                transaction_id=existing.transaction_id,
                                status="already_synced",
                            )
                        )
                        savepoint.commit()
                        continue

                # Process transaction atomically within savepoint
                tx = cls.process_pos_transaction(
                    db=db,
                    store_id=target_store_id,
                    cashier=cashier,
                    pos_in=tx_in,
                    offline_sync=True,
                    auto_commit=False,
                )
                db.flush()
                savepoint.commit()
                synced_count += 1
                results.append(
                    OfflineSyncTransactionResult(
                        client_offline_id=client_offline_id,
                        invoice_number=tx.invoice_number,
                        transaction_id=tx.transaction_id,
                        status="synced",
                    )
                )
            except InsufficientStockException as e:
                savepoint.rollback()
                failed_count += 1
                results.append(
                    OfflineSyncTransactionResult(
                        client_offline_id=client_offline_id,
                        status="failed_insufficient_stock",
                        error_message=f"Insufficient stock for {e.details.get('product_name') if hasattr(e, 'details') and e.details else 'item'}",
                    )
                )
            except Exception as e:
                savepoint.rollback()
                failed_count += 1
                results.append(
                    OfflineSyncTransactionResult(
                        client_offline_id=client_offline_id,
                        status="failed_error",
                        error_message=str(e),
                    )
                )

        db.commit()
        return OfflineSyncResponse(
            total_received=len(sync_req.transactions),
            synced_count=synced_count,
            already_synced_count=already_synced_count,
            failed_count=failed_count,
            results=results,
        )

    @classmethod
    def get_transaction_by_id(cls, db: Session, transaction_id: uuid.UUID, store_id: uuid.UUID | None = None) -> Transaction:
        query = db.query(Transaction).filter(Transaction.transaction_id == transaction_id)
        if store_id:
            query = query.filter(Transaction.store_id == store_id)
        tx = query.first()
        if not tx:
            raise EntityNotFoundException("Transaction in store", transaction_id)
        return tx

    @classmethod
    def list_transactions(
        cls,
        db: Session,
        store_id: uuid.UUID,
        search: str | None = None,
        date_filter: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Transaction]:
        query = db.query(Transaction).filter(Transaction.store_id == store_id)

        if search and search.strip():
            term = f"%{search.strip()}%"
            query = query.filter(
                (Transaction.invoice_number.ilike(term))
                | (Transaction.customer_name.ilike(term))
                | (Transaction.customer_phone.ilike(term))
            )

        now_utc = datetime.now(timezone.utc)
        today = now_utc.date()

        if date_filter:
            df = date_filter.lower().strip()
            if df == "today":
                start_dt = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
                query = query.filter(Transaction.created_at >= start_dt)
            elif df == "yesterday":
                yesterday = today - timedelta(days=1)
                start_dt = datetime.combine(yesterday, datetime.min.time(), tzinfo=timezone.utc)
                end_dt = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
                query = query.filter(Transaction.created_at >= start_dt, Transaction.created_at < end_dt)
            elif df in ["this_week", "week"]:
                start_week = today - timedelta(days=today.weekday())
                start_dt = datetime.combine(start_week, datetime.min.time(), tzinfo=timezone.utc)
                query = query.filter(Transaction.created_at >= start_dt)
            elif df in ["this_month", "month"]:
                start_month = today.replace(day=1)
                start_dt = datetime.combine(start_month, datetime.min.time(), tzinfo=timezone.utc)
                query = query.filter(Transaction.created_at >= start_dt)

        if start_date:
            start_dt = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
            query = query.filter(Transaction.created_at >= start_dt)

        if end_date:
            end_dt = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
            query = query.filter(Transaction.created_at < end_dt)

        return query.order_by(Transaction.created_at.desc()).offset(offset).limit(limit).all()

    @classmethod
    def get_receipt_data(cls, db: Session, transaction_id: uuid.UUID, store_id: uuid.UUID | None = None) -> ReceiptResponse:
        """
        Produces the standardized raw structured transaction data needed for
        React Native client-side PDF construction and Android PrintManager.
        Strictly isolated to store_id tenant.
        """
        tx = cls.get_transaction_by_id(db, transaction_id, store_id=store_id)
        store = tx.store
        signature_b64 = StoreService.get_signature_base64(store)
        logo_b64 = StoreService.get_logo_base64(store)

        store_header = StoreReceiptHeader(
            store_id=store.store_id,
            store_name=store.name,
            owner_name=store.owner_name,
            phone_number=store.phone_number,
            address=store.address,
            email=store.email,
            state=getattr(store, "state", None) or "19-West Bengal",
            logo_url=store.logo_url,
            has_logo=store.logo_data is not None or store.logo_url is not None,
            logo_base64=logo_b64,
            has_signature=store.authorized_signature_data is not None,
            authorized_signature_base64=signature_b64,
        )

        item_responses: list[TransactionItemResponse] = []
        for item in tx.items:
            allocs = [
                BatchAllocationResponse(
                    allocation_id=a.allocation_id,
                    batch_id=a.batch_id,
                    batch_identifier=a.batch_identifier,
                    quantity_deducted=a.quantity_deducted,
                    expiry_date=a.expiry_date,
                )
                for a in item.allocations
            ]
            item_responses.append(
                TransactionItemResponse(
                    item_id=item.item_id,
                    product_id=item.product_id,
                    product_name=item.product_name,
                    category=item.category,
                    unit=item.unit,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    item_discount_pct=item.item_discount_pct,
                    category_discount_pct=item.category_discount_pct,
                    cashback_amount=getattr(item, "cashback_amount", Decimal("0.00")),
                    cashback_pct=getattr(item, "cashback_pct", Decimal("0.00")),
                    discount_amount=getattr(item, "discount_amount", item.line_discount_amount),
                    discount_pct=getattr(item, "discount_pct", Decimal("0.00")),
                    line_base_total=item.line_base_total,
                    line_discount_amount=item.line_discount_amount,
                    line_total=item.line_total,
                    allocations=allocs,
                )
            )

        amount_words = number_to_words_inr(tx.final_total)
        you_saved = quantize_currency(
            (tx.total_discount_amount or Decimal("0.00"))
            + (tx.item_discount_amount or Decimal("0.00"))
            + (tx.category_discount_amount or Decimal("0.00"))
        )

        received_amt = getattr(tx, "received_amount", None)
        if received_amt is None:
            received_amt = Decimal("0.00") if tx.payment_method == PaymentMethod.CREDIT.value else tx.final_total
        balance_amt = getattr(tx, "balance_amount", None)
        if balance_amt is None:
            balance_amt = max(Decimal("0.00"), tx.final_total - received_amt)

        return ReceiptResponse(
            store=store_header,
            invoice_number=tx.invoice_number,
            invoice_seq=getattr(tx, "invoice_seq", None),
            transaction_id=tx.transaction_id,
            date=tx.created_at,
            cashier_name=tx.cashier.name if tx.cashier else "Store Staff",
            customer_name=tx.customer_name or "Walk-in Customer",
            customer_phone=tx.customer_phone,
            items=item_responses,
            subtotal=tx.subtotal,
            item_discount_amount=tx.item_discount_amount,
            category_discount_amount=tx.category_discount_amount,
            total_discount_percentage=tx.total_discount_percentage,
            total_discount_amount=tx.total_discount_amount,
            total_cashback_amount=getattr(tx, "total_cashback_amount", Decimal("0.00")),
            tax_amount=tx.tax_amount,
            final_total=tx.final_total,
            received_amount=received_amt,
            balance_amount=balance_amt,
            amount_in_words=amount_words,
            you_saved_amount=you_saved,
            payment_method=tx.payment_method,
            payment_status=tx.payment_status,
        )

    @classmethod
    def to_transaction_response(cls, tx: Transaction) -> TransactionResponse:
        item_responses: list[TransactionItemResponse] = []
        for item in tx.items:
            allocs = [
                BatchAllocationResponse(
                    allocation_id=a.allocation_id,
                    batch_id=a.batch_id,
                    batch_identifier=a.batch_identifier,
                    quantity_deducted=a.quantity_deducted,
                    expiry_date=a.expiry_date,
                )
                for a in item.allocations
            ]
            item_responses.append(
                TransactionItemResponse(
                    item_id=item.item_id,
                    product_id=item.product_id,
                    product_name=item.product_name,
                    category=item.category,
                    unit=item.unit,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    item_discount_pct=item.item_discount_pct,
                    category_discount_pct=item.category_discount_pct,
                    cashback_amount=getattr(item, "cashback_amount", Decimal("0.00")),
                    cashback_pct=getattr(item, "cashback_pct", Decimal("0.00")),
                    discount_amount=getattr(item, "discount_amount", item.line_discount_amount),
                    discount_pct=getattr(item, "discount_pct", Decimal("0.00")),
                    line_base_total=item.line_base_total,
                    line_discount_amount=item.line_discount_amount,
                    line_total=item.line_total,
                    allocations=allocs,
                )
            )

        amount_words = number_to_words_inr(tx.final_total)
        you_saved = quantize_currency(
            (tx.total_discount_amount or Decimal("0.00"))
            + (tx.item_discount_amount or Decimal("0.00"))
            + (tx.category_discount_amount or Decimal("0.00"))
        )

        received_amt = getattr(tx, "received_amount", None)
        if received_amt is None:
            received_amt = Decimal("0.00") if tx.payment_method == PaymentMethod.CREDIT.value else tx.final_total
        balance_amt = getattr(tx, "balance_amount", None)
        if balance_amt is None:
            balance_amt = max(Decimal("0.00"), tx.final_total - received_amt)

        return TransactionResponse(
            transaction_id=tx.transaction_id,
            store_id=tx.store_id,
            invoice_number=tx.invoice_number,
            invoice_seq=getattr(tx, "invoice_seq", None),
            cashier_id=tx.cashier_id,
            cashier_name=tx.cashier.name if tx.cashier else None,
            customer_name=tx.customer_name,
            customer_phone=tx.customer_phone,
            customer_email=tx.customer_email,
            subtotal=tx.subtotal,
            item_discount_amount=tx.item_discount_amount,
            category_discount_amount=tx.category_discount_amount,
            total_discount_percentage=tx.total_discount_percentage,
            total_discount_amount=tx.total_discount_amount,
            total_cashback_amount=getattr(tx, "total_cashback_amount", Decimal("0.00")),
            tax_amount=tx.tax_amount,
            final_total=tx.final_total,
            received_amount=received_amt,
            balance_amount=balance_amt,
            amount_in_words=amount_words,
            you_saved_amount=you_saved,
            payment_method=tx.payment_method,
            payment_status=tx.payment_status,
            notes=tx.notes,
            offline_synced=tx.offline_synced,
            client_offline_id=tx.client_offline_id,
            created_at=tx.created_at,
            items=item_responses,
        )
