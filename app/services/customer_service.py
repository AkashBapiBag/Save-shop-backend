import uuid
from decimal import Decimal

from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from app.core.exceptions import EntityNotFoundException, ValidationException
from app.models.customer import Customer, CustomerPayment, customer_stores
from app.models.transaction import PaymentStatus, Transaction
from app.models.user import User
from app.schemas.customer import (
    CustomerCreate,
    CustomerHistoryResponse,
    CustomerPaymentCreate,
    CustomerPaymentResponse,
    CustomerResponse,
    CustomerTransactionHistoryItem,
    CustomerUpdate,
)
from app.utils.unit_calc import quantize_currency


class CustomerService:
    @classmethod
    def _to_response(
        cls,
        customer: Customer,
        store_id: uuid.UUID,
        total_orders: int = 0,
        total_spent: Decimal = Decimal("0.00"),
        total_due: Decimal = Decimal("0.00"),
        advance_balance: Decimal | None = None,
        last_order_date=None,
    ) -> CustomerResponse:
        linked_store_ids = [s.store_id for s in customer.stores] if customer.stores else [customer.store_id]
        if store_id not in linked_store_ids:
            linked_store_ids.append(store_id)

        due_val = quantize_currency(Decimal(str(total_due or "0.00")))
        adv_val = quantize_currency(
            Decimal(str(advance_balance if advance_balance is not None else getattr(customer, "advance_balance", 0) or "0.00"))
        )
        net_val = quantize_currency(due_val - adv_val)

        return CustomerResponse(
            customer_id=customer.customer_id,
            store_id=store_id,
            name=customer.name,
            phone=customer.phone,
            email=customer.email,
            address=customer.address,
            notes=customer.notes,
            created_at=customer.created_at,
            updated_at=customer.updated_at,
            total_orders=int(total_orders or 0),
            total_spent=Decimal(str(total_spent or "0.00")),
            total_due=due_val,
            advance_balance=adv_val,
            net_balance=net_val,
            last_order_date=last_order_date,
            is_multi_store=len(linked_store_ids) > 1,
            store_ids=linked_store_ids,
        )

    @classmethod
    def link_customer_to_store(
        cls,
        db: Session,
        customer_id: uuid.UUID,
        store_id: uuid.UUID,
    ) -> Customer:
        """
        Links an existing customer profile to a store via customer_stores association.
        Idempotent: does nothing if already linked.
        """
        customer = db.query(Customer).filter(Customer.customer_id == customer_id).first()
        if not customer:
            raise EntityNotFoundException("Customer", customer_id)

        existing_link = (
            db.query(customer_stores)
            .filter(
                customer_stores.c.customer_id == customer_id,
                customer_stores.c.store_id == store_id,
            )
            .first()
        )
        if not existing_link:
            db.execute(customer_stores.insert().values(customer_id=customer_id, store_id=store_id))
            db.commit()
            db.refresh(customer)

        return customer

    @classmethod
    def list_customers(
        cls,
        db: Session,
        store_id: uuid.UUID,
        search: str | None = None,
        sort_by: str = "recent",
        filter_dues: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CustomerResponse]:
        """
        Retrieves store customers with aggregated purchasing metrics (total orders, total spent, total due, last purchase date).
        Supports common multi-store customers via customer_stores association.
        Supports live search on name or phone, and filtering by outstanding dues.
        """
        stats_subq = (
            db.query(
                Transaction.customer_id,
                func.count(Transaction.transaction_id).label("total_orders"),
                func.coalesce(func.sum(Transaction.final_total), Decimal("0.00")).label("total_spent"),
                func.coalesce(
                    func.sum(
                        case(
                            (Transaction.balance_amount > 0, Transaction.balance_amount),
                            else_=Decimal("0.00"),
                        )
                    ),
                    Decimal("0.00"),
                ).label("total_due"),
                func.max(Transaction.created_at).label("last_order_date"),
            )
            .filter(Transaction.store_id == store_id, Transaction.customer_id.isnot(None))
            .group_by(Transaction.customer_id)
            .subquery()
        )

        store_cond = or_(Customer.store_id == store_id, customer_stores.c.store_id == store_id)
        total_orders_col = func.coalesce(stats_subq.c.total_orders, 0).label("total_orders")
        total_spent_col = func.coalesce(stats_subq.c.total_spent, Decimal("0.00")).label("total_spent")
        total_due_col = func.coalesce(stats_subq.c.total_due, Decimal("0.00")).label("total_due")
        last_order_date_col = stats_subq.c.last_order_date.label("last_order_date")
        effective_last_date = func.coalesce(stats_subq.c.last_order_date, Customer.created_at).label(
            "effective_last_date"
        )

        query = (
            db.query(
                Customer,
                total_orders_col,
                total_spent_col,
                total_due_col,
                last_order_date_col,
                effective_last_date,
            )
            .outerjoin(stats_subq, Customer.customer_id == stats_subq.c.customer_id)
            .outerjoin(customer_stores, Customer.customer_id == customer_stores.c.customer_id)
            .filter(store_cond)
            .distinct()
        )

        if filter_dues or sort_by == "dues":
            query = query.filter(total_due_col > Decimal("0.00"))

        if search and search.strip():
            term = f"%{search.strip()}%"
            query = query.filter((Customer.name.ilike(term)) | (Customer.phone.ilike(term)))

        # Sorting
        if sort_by == "name":
            query = query.order_by(Customer.name.asc())
        elif sort_by == "orders":
            query = query.order_by(total_orders_col.desc(), Customer.name.asc())
        elif sort_by == "spent":
            query = query.order_by(total_spent_col.desc(), Customer.name.asc())
        elif sort_by == "dues":
            query = query.order_by(total_due_col.desc(), Customer.name.asc())
        else:  # "recent" default
            query = query.order_by(
                effective_last_date.desc(),
                Customer.created_at.desc(),
            )

        rows = query.offset(offset).limit(limit).all()

        results: list[CustomerResponse] = []
        for row in rows:
            customer = row[0]
            total_orders = row[1]
            total_spent = row[2]
            total_due = row[3]
            last_order_date = row[4]
            results.append(
                cls._to_response(
                    customer=customer,
                    store_id=store_id,
                    total_orders=int(total_orders or 0),
                    total_spent=Decimal(str(total_spent or "0.00")),
                    total_due=Decimal(str(total_due or "0.00")),
                    advance_balance=customer.advance_balance,
                    last_order_date=last_order_date,
                )
            )

        return results

    @classmethod
    def create_customer(
        cls,
        db: Session,
        store_id: uuid.UUID,
        customer_in: CustomerCreate,
    ) -> CustomerResponse:
        """
        Creates a new customer profile under the active store tenant, or links an existing customer
        if they already exist in another store with the same phone number.
        Mobile number is optional.
        """
        clean_name = customer_in.name.strip()
        if not clean_name:
            raise ValidationException("Customer name is required.")

        clean_phone = customer_in.phone.strip() if customer_in.phone and customer_in.phone.strip() else None

        if clean_phone:
            # Check for existing customer with same phone in THIS store: reuse and proceed
            existing_in_store = (
                db.query(Customer)
                .outerjoin(customer_stores, Customer.customer_id == customer_stores.c.customer_id)
                .filter(
                    Customer.phone == clean_phone,
                    or_(Customer.store_id == store_id, customer_stores.c.store_id == store_id),
                )
                .first()
            )
            if existing_in_store:
                return cls.get_customer_by_id(db, existing_in_store.customer_id, store_id)

            # Check if customer exists in ANOTHER store: link to this store and proceed
            existing_global = db.query(Customer).filter(Customer.phone == clean_phone).first()
            if existing_global:
                cls.link_customer_to_store(db, existing_global.customer_id, store_id)
                return cls.get_customer_by_id(db, existing_global.customer_id, store_id)

        customer = Customer(
            customer_id=uuid.uuid4(),
            store_id=store_id,
            name=clean_name,
            phone=clean_phone,
            email=str(customer_in.email).strip().lower() if customer_in.email else None,
            address=customer_in.address.strip() if customer_in.address else None,
            notes=customer_in.notes.strip() if customer_in.notes else None,
            advance_balance=Decimal("0.00"),
        )
        db.add(customer)
        db.commit()
        db.refresh(customer)

        cls.link_customer_to_store(db, customer.customer_id, store_id)

        return cls._to_response(
            customer=customer,
            store_id=store_id,
            total_orders=0,
            total_spent=Decimal("0.00"),
            total_due=Decimal("0.00"),
            advance_balance=Decimal("0.00"),
            last_order_date=None,
        )

    @classmethod
    def get_customer_by_id(
        cls,
        db: Session,
        customer_id: uuid.UUID,
        store_id: uuid.UUID,
    ) -> CustomerResponse:
        """
        Retrieves single customer profile along with aggregate order and due stats.
        Strictly requires customer to belong to the store.
        """
        customer = (
            db.query(Customer)
            .outerjoin(customer_stores, Customer.customer_id == customer_stores.c.customer_id)
            .filter(
                Customer.customer_id == customer_id,
                or_(Customer.store_id == store_id, customer_stores.c.store_id == store_id),
            )
            .first()
        )
        if not customer:
            raise EntityNotFoundException("Customer in store", customer_id)

        stats = (
            db.query(
                func.count(Transaction.transaction_id).label("total_orders"),
                func.coalesce(func.sum(Transaction.final_total), Decimal("0.00")).label("total_spent"),
                func.coalesce(
                    func.sum(
                        case(
                            (Transaction.balance_amount > 0, Transaction.balance_amount),
                            else_=Decimal("0.00"),
                        )
                    ),
                    Decimal("0.00"),
                ).label("total_due"),
                func.max(Transaction.created_at).label("last_order_date"),
            )
            .filter(Transaction.customer_id == customer_id, Transaction.store_id == store_id)
            .first()
        )

        total_orders = stats.total_orders if stats else 0
        total_spent = stats.total_spent if stats else Decimal("0.00")
        total_due = stats.total_due if stats else Decimal("0.00")
        last_order_date = stats.last_order_date if stats else None

        return cls._to_response(
            customer=customer,
            store_id=store_id,
            total_orders=int(total_orders or 0),
            total_spent=Decimal(str(total_spent or "0.00")),
            total_due=Decimal(str(total_due or "0.00")),
            advance_balance=customer.advance_balance,
            last_order_date=last_order_date,
        )

    @classmethod
    def get_customer_history(
        cls,
        db: Session,
        customer_id: uuid.UUID,
        store_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> CustomerHistoryResponse:
        """
        Retrieves customer's lifetime purchase history and payment settlements.
        """
        customer_resp = cls.get_customer_by_id(db, customer_id, store_id)

        from app.models.store import Store

        txs = (
            db.query(Transaction, Store.name.label("store_name"))
            .outerjoin(Store, Transaction.store_id == Store.store_id)
            .filter(Transaction.customer_id == customer_id, Transaction.store_id == store_id)
            .order_by(Transaction.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

        items: list[CustomerTransactionHistoryItem] = []
        for tx, store_name in txs:
            items.append(
                CustomerTransactionHistoryItem(
                    transaction_id=tx.transaction_id,
                    invoice_number=tx.invoice_number,
                    invoice_seq=tx.invoice_seq,
                    store_id=tx.store_id,
                    store_name=store_name,
                    final_total=Decimal(str(tx.final_total or "0.00")),
                    received_amount=Decimal(str(tx.received_amount or "0.00")),
                    balance_amount=Decimal(str(tx.balance_amount or "0.00")),
                    payment_method=tx.payment_method,
                    payment_status=tx.payment_status,
                    items_count=len(tx.items) if tx.items else 0,
                    created_at=tx.created_at,
                )
            )

        # Retrieve past customer payments / settlements
        payments = (
            db.query(CustomerPayment, User.name.label("cashier_name"))
            .outerjoin(User, CustomerPayment.cashier_id == User.user_id)
            .filter(CustomerPayment.customer_id == customer_id, CustomerPayment.store_id == store_id)
            .order_by(CustomerPayment.created_at.desc())
            .limit(limit)
            .all()
        )
        payment_items = [
            CustomerPaymentResponse(
                payment_id=p.payment_id,
                store_id=p.store_id,
                customer_id=p.customer_id,
                cashier_id=p.cashier_id,
                cashier_name=c_name,
                payment_number=p.payment_number,
                amount=Decimal(str(p.amount or "0.00")),
                payment_method=p.payment_method,
                notes=p.notes,
                created_at=p.created_at,
            )
            for p, c_name in payments
        ]

        all_stores_stats = (
            db.query(
                func.count(Transaction.transaction_id).label("total_orders"),
                func.coalesce(func.sum(Transaction.final_total), Decimal("0.00")).label("total_spent"),
            )
            .filter(Transaction.customer_id == customer_id)
            .first()
        )

        all_orders = int(all_stores_stats.total_orders or 0) if all_stores_stats else customer_resp.total_orders
        all_spent = Decimal(str(all_stores_stats.total_spent or "0.00")) if all_stores_stats else customer_resp.total_spent

        return CustomerHistoryResponse(
            customer=customer_resp,
            transactions=items,
            payments=payment_items,
            total_orders=customer_resp.total_orders,
            total_spent=customer_resp.total_spent,
            total_due=customer_resp.total_due,
            advance_balance=customer_resp.advance_balance,
            net_balance=customer_resp.net_balance,
            all_stores_orders=all_orders,
            all_stores_spent=all_spent,
        )

    @classmethod
    def record_payment(
        cls,
        db: Session,
        store_id: uuid.UUID,
        customer_id: uuid.UUID,
        payment_in: CustomerPaymentCreate,
        cashier: User | None = None,
    ) -> CustomerPaymentResponse:
        """
        Records a customer payment to settle outstanding dues or add advance credit.
        Allocates payment FIFO against pending transactions, marking them PAID when balance hits 0.
        Any excess is credited to customer advance_balance.
        """
        customer = (
            db.query(Customer)
            .outerjoin(customer_stores, Customer.customer_id == customer_stores.c.customer_id)
            .filter(
                Customer.customer_id == customer_id,
                or_(Customer.store_id == store_id, customer_stores.c.store_id == store_id),
            )
            .first()
        )
        if not customer:
            raise EntityNotFoundException("Customer in store", customer_id)

        cls.link_customer_to_store(db, customer_id, store_id)

        amt = quantize_currency(Decimal(str(payment_in.amount)))
        if amt <= Decimal("0.00"):
            raise ValidationException("Payment amount must be greater than zero.")

        receipt_count = (
            db.query(func.count(CustomerPayment.payment_id))
            .filter(CustomerPayment.store_id == store_id)
            .scalar()
            or 0
        )
        payment_number = f"PAY-{receipt_count + 1:04d}"

        payment = CustomerPayment(
            payment_id=uuid.uuid4(),
            store_id=store_id,
            customer_id=customer_id,
            cashier_id=cashier.user_id if cashier else None,
            payment_number=payment_number,
            amount=amt,
            payment_method=str(
                payment_in.payment_method.value
                if hasattr(payment_in.payment_method, "value")
                else payment_in.payment_method
            ).upper(),
            notes=payment_in.notes.strip() if payment_in.notes else None,
        )
        db.add(payment)

        remaining = amt

        # Settle specific invoice if provided
        if payment_in.transaction_id:
            target_tx = (
                db.query(Transaction)
                .filter(
                    Transaction.transaction_id == payment_in.transaction_id,
                    Transaction.customer_id == customer_id,
                    Transaction.store_id == store_id,
                )
                .first()
            )
            if target_tx and target_tx.balance_amount > Decimal("0.00"):
                settle_amt = min(target_tx.balance_amount, remaining)
                target_tx.balance_amount = quantize_currency(target_tx.balance_amount - settle_amt)
                target_tx.received_amount = quantize_currency(target_tx.received_amount + settle_amt)
                if target_tx.balance_amount <= Decimal("0.00"):
                    target_tx.payment_status = PaymentStatus.PAID.value
                remaining = quantize_currency(remaining - settle_amt)

        # Allocate FIFO across oldest pending transactions
        if remaining > Decimal("0.00"):
            pending_txs = (
                db.query(Transaction)
                .filter(
                    Transaction.customer_id == customer_id,
                    Transaction.store_id == store_id,
                    Transaction.balance_amount > Decimal("0.00"),
                )
                .order_by(Transaction.created_at.asc())
                .all()
            )
            for tx in pending_txs:
                if remaining <= Decimal("0.00"):
                    break
                settle_amt = min(tx.balance_amount, remaining)
                tx.balance_amount = quantize_currency(tx.balance_amount - settle_amt)
                tx.received_amount = quantize_currency(tx.received_amount + settle_amt)
                if tx.balance_amount <= Decimal("0.00"):
                    tx.payment_status = PaymentStatus.PAID.value
                remaining = quantize_currency(remaining - settle_amt)

        # Excess beyond all pending dues goes to customer's advance balance
        if remaining > Decimal("0.00"):
            current_adv = Decimal(str(customer.advance_balance or "0.00"))
            customer.advance_balance = quantize_currency(current_adv + remaining)

        db.commit()
        db.refresh(payment)
        db.refresh(customer)

        return CustomerPaymentResponse(
            payment_id=payment.payment_id,
            store_id=payment.store_id,
            customer_id=payment.customer_id,
            cashier_id=payment.cashier_id,
            cashier_name=cashier.name if cashier else None,
            payment_number=payment.payment_number,
            amount=payment.amount,
            payment_method=payment.payment_method,
            notes=payment.notes,
            created_at=payment.created_at,
        )

    @classmethod
    def list_customer_payments(
        cls,
        db: Session,
        store_id: uuid.UUID,
        customer_id: uuid.UUID,
    ) -> list[CustomerPaymentResponse]:
        payments = (
            db.query(CustomerPayment, User.name.label("cashier_name"))
            .outerjoin(User, CustomerPayment.cashier_id == User.user_id)
            .filter(CustomerPayment.customer_id == customer_id, CustomerPayment.store_id == store_id)
            .order_by(CustomerPayment.created_at.desc())
            .all()
        )
        return [
            CustomerPaymentResponse(
                payment_id=p.payment_id,
                store_id=p.store_id,
                customer_id=p.customer_id,
                cashier_id=p.cashier_id,
                cashier_name=c_name,
                payment_number=p.payment_number,
                amount=Decimal(str(p.amount or "0.00")),
                payment_method=p.payment_method,
                notes=p.notes,
                created_at=p.created_at,
            )
            for p, c_name in payments
        ]

    @classmethod
    def update_customer(
        cls,
        db: Session,
        customer_id: uuid.UUID,
        store_id: uuid.UUID,
        customer_in: CustomerUpdate,
    ) -> CustomerResponse:
        """
        Updates customer profile details.
        """
        customer = (
            db.query(Customer)
            .outerjoin(customer_stores, Customer.customer_id == customer_stores.c.customer_id)
            .filter(
                Customer.customer_id == customer_id,
                or_(Customer.store_id == store_id, customer_stores.c.store_id == store_id),
            )
            .first()
        )
        if not customer:
            raise EntityNotFoundException("Customer in store", customer_id)

        if customer_in.phone is not None:
            clean_phone = customer_in.phone.strip() if customer_in.phone.strip() else None
            if clean_phone and clean_phone != customer.phone:
                existing = (
                    db.query(Customer)
                    .outerjoin(customer_stores, Customer.customer_id == customer_stores.c.customer_id)
                    .filter(
                        Customer.phone == clean_phone,
                        Customer.customer_id != customer_id,
                        or_(Customer.store_id == store_id, customer_stores.c.store_id == store_id),
                    )
                    .first()
                )
                if existing:
                    raise ValidationException(f"A customer with phone '{clean_phone}' already exists ({existing.name}).")
                customer.phone = clean_phone
            elif clean_phone is None:
                customer.phone = None

        if customer_in.name is not None:
            clean_name = customer_in.name.strip()
            if not clean_name:
                raise ValidationException("Customer name cannot be empty.")
            customer.name = clean_name

        if customer_in.email is not None:
            customer.email = str(customer_in.email).strip().lower() if customer_in.email else None
        if customer_in.address is not None:
            customer.address = customer_in.address.strip() if customer_in.address else None
        if customer_in.notes is not None:
            customer.notes = customer_in.notes.strip() if customer_in.notes else None

        db.commit()
        db.refresh(customer)

        return cls.get_customer_by_id(db, customer.customer_id, store_id)
