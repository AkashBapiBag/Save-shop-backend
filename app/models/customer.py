import uuid

from sqlalchemy import Column, ForeignKey, Index, Numeric, String, Table, Text
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.models.base import GUID, TimestampMixin

# Many-to-many association allowing a customer to belong to multiple stores
customer_stores = Table(
    "customer_stores",
    Base.metadata,
    Column("customer_id", GUID(), ForeignKey("customers.customer_id", ondelete="CASCADE"), primary_key=True),
    Column("store_id", GUID(), ForeignKey("stores.store_id", ondelete="CASCADE"), primary_key=True),
)


class Customer(Base, TimestampMixin):
    __tablename__ = "customers"
    __table_args__ = (
        Index("ix_customers_store_name", "store_id", "name"),
        Index("ix_customers_store_phone", "store_id", "phone"),
    )

    customer_id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    store_id = Column(GUID(), ForeignKey("stores.store_id", ondelete="CASCADE"), index=True, nullable=False)
    name = Column(String(255), index=True, nullable=False)
    phone = Column(String(50), index=True, nullable=True)
    email = Column(String(255), nullable=True)
    address = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    advance_balance = Column(Numeric(12, 2), default=0.00, nullable=False)

    # Relationships
    store = relationship("Store", foreign_keys=[store_id])
    stores = relationship("Store", secondary=customer_stores, back_populates="customers")
    transactions = relationship("Transaction", back_populates="customer")
    payments = relationship(
        "CustomerPayment",
        back_populates="customer",
        cascade="all, delete-orphan",
        order_by="desc(CustomerPayment.created_at)",
    )


class CustomerPayment(Base, TimestampMixin):
    __tablename__ = "customer_payments"
    __table_args__ = (
        Index("ix_customer_payments_store_cust", "store_id", "customer_id"),
        Index("ix_customer_payments_created", "store_id", "created_at"),
    )

    payment_id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    store_id = Column(GUID(), ForeignKey("stores.store_id", ondelete="CASCADE"), index=True, nullable=False)
    customer_id = Column(GUID(), ForeignKey("customers.customer_id", ondelete="CASCADE"), index=True, nullable=False)
    cashier_id = Column(GUID(), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)
    payment_number = Column(String(100), index=True, nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    payment_method = Column(String(50), default="CASH", nullable=False)
    notes = Column(Text, nullable=True)

    # Relationships
    store = relationship("Store", foreign_keys=[store_id])
    customer = relationship("Customer", back_populates="payments")
    cashier = relationship("User", foreign_keys=[cashier_id])
