import uuid
from enum import Enum

from sqlalchemy import Boolean, Column, Date, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.models.base import GUID, TimestampMixin


class PaymentMethod(str, Enum):
    CASH = "CASH"
    CARD = "CARD"
    UPI = "UPI"
    CREDIT = "CREDIT"


class PaymentStatus(str, Enum):
    PAID = "PAID"
    PENDING = "PENDING"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"


class Transaction(Base, TimestampMixin):
    __tablename__ = "transactions"
    __table_args__ = (
        Index("ix_transactions_store_created", "store_id", "created_at"),
        Index("ix_transactions_store_invoice", "store_id", "invoice_number"),
        Index("ix_transactions_store_client_offline", "store_id", "client_offline_id"),
        UniqueConstraint("store_id", "invoice_number", name="uq_transactions_store_invoice"),
        UniqueConstraint("store_id", "invoice_seq", name="uq_transactions_store_invoice_seq"),
    )

    transaction_id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    store_id = Column(GUID(), ForeignKey("stores.store_id", ondelete="RESTRICT"), index=True, nullable=False)
    invoice_seq = Column(Integer, nullable=True, index=True)
    invoice_number = Column(String(100), index=True, nullable=False)
    cashier_id = Column(GUID(), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)

    # Customer info
    customer_name = Column(String(255), nullable=True)
    customer_phone = Column(String(50), nullable=True)
    customer_email = Column(String(255), nullable=True)

    # Financial breakdown
    subtotal = Column(Numeric(12, 2), nullable=False)  # Base total before any discounts
    item_discount_amount = Column(Numeric(12, 2), default=0.00, nullable=False)
    category_discount_amount = Column(Numeric(12, 2), default=0.00, nullable=False)
    total_discount_percentage = Column(Numeric(5, 2), default=0.00, nullable=False)
    total_discount_amount = Column(Numeric(12, 2), default=0.00, nullable=False)
    total_cashback_amount = Column(Numeric(12, 2), default=0.00, nullable=False)
    tax_amount = Column(Numeric(12, 2), default=0.00, nullable=False)
    final_total = Column(Numeric(12, 2), nullable=False)
    received_amount = Column(Numeric(12, 2), default=0.00, nullable=False)
    balance_amount = Column(Numeric(12, 2), default=0.00, nullable=False)

    payment_method = Column(String(50), default=PaymentMethod.CASH.value, nullable=False)
    payment_status = Column(String(50), default=PaymentStatus.PAID.value, nullable=False)
    notes = Column(Text, nullable=True)

    # Offline Sync Reconciliation
    offline_synced = Column(Boolean, default=False, nullable=False)
    client_offline_id = Column(String(255), unique=True, index=True, nullable=True)

    # Relationships
    store = relationship("Store", back_populates="transactions")
    cashier = relationship("User", back_populates="transactions")
    items = relationship(
        "TransactionItem",
        back_populates="transaction",
        cascade="all, delete-orphan",
    )


class TransactionItem(Base, TimestampMixin):
    __tablename__ = "transaction_items"

    item_id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    transaction_id = Column(GUID(), ForeignKey("transactions.transaction_id", ondelete="CASCADE"), index=True, nullable=False)
    product_id = Column(GUID(), ForeignKey("products.product_id", ondelete="RESTRICT"), index=True, nullable=False)

    product_name = Column(String(255), nullable=False)
    category = Column(String(100), default="General", nullable=False)
    unit = Column(String(20), default="PIECE", nullable=False)
    quantity = Column(Numeric(12, 3), nullable=False)
    unit_price = Column(Numeric(12, 2), nullable=False)

    # Discounts & Cashback
    item_discount_pct = Column(Numeric(5, 2), default=0.00, nullable=False)
    category_discount_pct = Column(Numeric(5, 2), default=0.00, nullable=False)
    cashback_amount = Column(Numeric(12, 2), default=0.00, nullable=False)
    cashback_pct = Column(Numeric(5, 2), default=0.00, nullable=False)
    discount_amount = Column(Numeric(12, 2), default=0.00, nullable=False)
    discount_pct = Column(Numeric(5, 2), default=0.00, nullable=False)

    # Subtotals
    line_base_total = Column(Numeric(12, 2), nullable=False)  # qty * unit_price
    line_discount_amount = Column(Numeric(12, 2), default=0.00, nullable=False)
    line_total = Column(Numeric(12, 2), nullable=False)  # price after item & category discounts

    # Relationships
    transaction = relationship("Transaction", back_populates="items")
    product = relationship("Product", back_populates="transaction_items")
    allocations = relationship(
        "TransactionBatchAllocation",
        back_populates="transaction_item",
        cascade="all, delete-orphan",
    )


class TransactionBatchAllocation(Base, TimestampMixin):
    """
    Tracks exactly which batch was depleted for each transaction line item (FEFO audit trail).
    """

    __tablename__ = "transaction_batch_allocations"

    allocation_id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    transaction_item_id = Column(GUID(), ForeignKey("transaction_items.item_id", ondelete="CASCADE"), index=True, nullable=False)
    batch_id = Column(GUID(), ForeignKey("batches.batch_id", ondelete="RESTRICT"), index=True, nullable=False)
    product_id = Column(GUID(), ForeignKey("products.product_id", ondelete="RESTRICT"), nullable=False)

    quantity_deducted = Column(Numeric(12, 3), nullable=False)
    batch_identifier = Column(String(100), nullable=False)
    expiry_date = Column(Date, nullable=False)

    # Relationships
    transaction_item = relationship("TransactionItem", back_populates="allocations")
    batch = relationship("Batch", back_populates="allocations")
