import uuid

from sqlalchemy import Boolean, Column, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.models.base import GUID, TimestampMixin


class StockTransfer(Base, TimestampMixin):
    __tablename__ = "stock_transfers"
    __table_args__ = (
        Index("ix_stock_transfers_source_store", "source_store_id"),
        Index("ix_stock_transfers_dest_store", "destination_store_id"),
        Index("ix_stock_transfers_created_at", "created_at"),
    )

    transfer_id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    transfer_number = Column(String(50), unique=True, index=True, nullable=False)
    source_store_id = Column(GUID(), ForeignKey("stores.store_id", ondelete="CASCADE"), nullable=False)
    destination_store_id = Column(GUID(), ForeignKey("stores.store_id", ondelete="CASCADE"), nullable=False)
    created_by_user_id = Column(GUID(), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)
    transferred_by_name = Column(String(255), nullable=False)
    status = Column(String(50), default="COMPLETED", nullable=False)
    notes = Column(Text, nullable=True)
    total_items = Column(Integer, default=1, nullable=False)
    total_quantity = Column(Numeric(12, 3), default=0.000, nullable=False)

    # Relationships
    source_store = relationship("Store", foreign_keys=[source_store_id])
    destination_store = relationship("Store", foreign_keys=[destination_store_id])
    created_by = relationship("User", foreign_keys=[created_by_user_id])
    items = relationship("StockTransferItem", back_populates="transfer", cascade="all, delete-orphan")


class StockTransferItem(Base, TimestampMixin):
    __tablename__ = "stock_transfer_items"
    __table_args__ = (
        Index("ix_stock_transfer_items_transfer", "transfer_id"),
        Index("ix_stock_transfer_items_source_prod", "source_product_id"),
        Index("ix_stock_transfer_items_dest_prod", "destination_product_id"),
    )

    item_id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    transfer_id = Column(GUID(), ForeignKey("stock_transfers.transfer_id", ondelete="CASCADE"), nullable=False)
    source_product_id = Column(GUID(), ForeignKey("products.product_id", ondelete="SET NULL"), nullable=True)
    destination_product_id = Column(GUID(), ForeignKey("products.product_id", ondelete="SET NULL"), nullable=True)
    product_name = Column(String(255), nullable=False)
    category = Column(String(100), default="General", nullable=False)
    unit = Column(String(20), default="PIECE", nullable=False)
    quantity = Column(Numeric(12, 3), nullable=False)
    auto_created_product = Column(Boolean, default=False, nullable=False)

    # Relationships
    transfer = relationship("StockTransfer", back_populates="items")
    source_product = relationship("Product", foreign_keys=[source_product_id])
    destination_product = relationship("Product", foreign_keys=[destination_product_id])
