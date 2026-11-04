import uuid
from decimal import Decimal

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.exceptions import EntityNotFoundException, ValidationException
from app.models.customer import Customer, customer_stores
from app.models.transaction import Transaction
from app.schemas.customer import (
    CustomerCreate,
    CustomerHistoryResponse,
    CustomerResponse,
    CustomerTransactionHistoryItem,
    CustomerUpdate,
)


class CustomerService:
    @classmethod
    def _to_response(
        cls,
        customer: Customer,
        store_id: uuid.UUID,
        total_orders: int = 0,
        total_spent: Decimal = Decimal("0.00"),
        last_order_date=None,
    ) -> CustomerResponse:
        linked_store_ids = [s.store_id for s in customer.stores] if customer.stores else [customer.store_id]
        if store_id not in linked_store_ids:
            linked_store_ids.append(store_id)

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
        limit: int = 100,
        offset: int = 0,
    ) -> list[CustomerResponse]:
        """
        Retrieves store customers with aggregated purchasing metrics (total orders, total spent, last purchase date).
        Supports common multi-store customers via customer_stores association.
        Supports live search on name or phone.
        """
        stats_subq = (
            db.query(
                Transaction.customer_id,
                func.count(Transaction.transaction_id).label("total_orders"),
                func.coalesce(func.sum(Transaction.final_total), Decimal("0.00")).label("total_spent"),
                func.max(Transaction.created_at).label("last_order_date"),
            )
            .filter(Transaction.store_id == store_id, Transaction.customer_id.isnot(None))
            .group_by(Transaction.customer_id)
            .subquery()
        )

        store_cond = or_(Customer.store_id == store_id, customer_stores.c.store_id == store_id)
        total_orders_col = func.coalesce(stats_subq.c.total_orders, 0).label("total_orders")
        total_spent_col = func.coalesce(stats_subq.c.total_spent, Decimal("0.00")).label("total_spent")
        last_order_date_col = stats_subq.c.last_order_date.label("last_order_date")
        effective_last_date = func.coalesce(stats_subq.c.last_order_date, Customer.created_at).label(
            "effective_last_date"
        )

        query = (
            db.query(
                Customer,
                total_orders_col,
                total_spent_col,
                last_order_date_col,
                effective_last_date,
            )
            .outerjoin(stats_subq, Customer.customer_id == stats_subq.c.customer_id)
            .outerjoin(customer_stores, Customer.customer_id == customer_stores.c.customer_id)
            .filter(store_cond)
            .distinct()
        )

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
            last_order_date = row[3]
            results.append(
                cls._to_response(
                    customer=customer,
                    store_id=store_id,
                    total_orders=int(total_orders or 0),
                    total_spent=Decimal(str(total_spent or "0.00")),
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
                # User is already saved in database: cool, proceed with existing customer!
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
        Retrieves single customer profile along with aggregate order stats.
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
                func.max(Transaction.created_at).label("last_order_date"),
            )
            .filter(Transaction.customer_id == customer_id, Transaction.store_id == store_id)
            .first()
        )

        total_orders = stats.total_orders if stats else 0
        total_spent = stats.total_spent if stats else Decimal("0.00")
        last_order_date = stats.last_order_date if stats else None

        return cls._to_response(
            customer=customer,
            store_id=store_id,
            total_orders=int(total_orders or 0),
            total_spent=Decimal(str(total_spent or "0.00")),
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
        Retrieves customer's lifetime purchase history with both store-specific and cross-store metrics.
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
            total_orders=customer_resp.total_orders,
            total_spent=customer_resp.total_spent,
            all_stores_orders=all_orders,
            all_stores_spent=all_spent,
        )

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
