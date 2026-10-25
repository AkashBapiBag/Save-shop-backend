import uuid
from enum import Enum

from sqlalchemy import Boolean, Column, Date, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.models.base import GUID, TimestampMixin


class UnitEnum(str, Enum):
    KG = "KG"
    ML = "ML"
    GRAM = "GRAM"
    DOZEN = "DOZEN"
    PIECE = "PIECE"
    LITER = "LITER"
    PACKET = "PACKET"
    BOX = "BOX"
    BOTTLE = "BOTTLE"
    METER = "METER"
    CAN = "CAN"


class Product(Base, TimestampMixin):
    __tablename__ = "products"
    __table_args__ = (
        Index("ix_products_store_category", "store_id", "category"),
        Index("ix_products_store_name", "store_id", "name"),
        Index("ix_products_store_barcode", "store_id", "barcode"),
    )

    product_id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    store_id = Column(GUID(), ForeignKey("stores.store_id", ondelete="CASCADE"), index=True, nullable=False)
    name = Column(String(255), index=True, nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(100), default="General", index=True, nullable=False)
    default_unit = Column(String(20), default=UnitEnum.PIECE.value, nullable=False)
    selling_price = Column(Numeric(12, 2), nullable=False)
    cost_price = Column(Numeric(12, 2), default=0.00, nullable=False)
    min_stock_alert_threshold = Column(Numeric(12, 3), default=10.000, nullable=False)
    barcode = Column(String(100), index=True, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    # Relationships
    store = relationship("Store", back_populates="products")
    batches = relationship(
        "Batch",
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="Batch.expiry_date.asc(), Batch.purchase_date.asc()",
    )
    transaction_items = relationship("TransactionItem", back_populates="product")


class Batch(Base, TimestampMixin):
    __tablename__ = "batches"
    __table_args__ = (
        Index("ix_batches_store_expiry", "store_id", "expiry_date"),
        Index("ix_batches_store_product", "store_id", "product_id"),
        Index("ix_batches_store_identifier", "store_id", "batch_identifier"),
    )

    batch_id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    product_id = Column(GUID(), ForeignKey("products.product_id", ondelete="CASCADE"), index=True, nullable=False)
    store_id = Column(GUID(), ForeignKey("stores.store_id", ondelete="CASCADE"), index=True, nullable=False)
    batch_identifier = Column(String(100), index=True, nullable=False)  # Supplier Lot #
    initial_quantity = Column(Numeric(12, 3), nullable=False)
    current_quantity = Column(Numeric(12, 3), nullable=False)  # Source of truth for stock
    purchase_price = Column(Numeric(12, 2), default=0.00, nullable=False)
    expiry_date = Column(Date, index=True, nullable=False)  # Crucial field for FEFO & expiry alerts
    purchase_date = Column(Date, index=True, nullable=False)

    # Relationships
    product = relationship("Product", back_populates="batches")
    store = relationship("Store", back_populates="batches")
    allocations = relationship("TransactionBatchAllocation", back_populates="batch")
