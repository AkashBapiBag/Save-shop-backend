import uuid

from sqlalchemy import Boolean, Column, LargeBinary, String, Text
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.models.base import GUID, TimestampMixin


class Store(Base, TimestampMixin):
    __tablename__ = "stores"

    store_id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), unique=True, index=True, nullable=False)
    owner_name = Column(String(255), nullable=True)
    phone_number = Column(String(50), nullable=True)
    address = Column(Text, nullable=True)
    state = Column(String(100), default="19-West Bengal", nullable=False)
    email = Column(String(255), nullable=True)
    logo_url = Column(String(1024), nullable=True)
    # BYTEA / BLOB for direct binary asset storage (logo & signature) in PostgreSQL
    logo_data = Column(LargeBinary, nullable=True)
    authorized_signature_data = Column(LargeBinary, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    # Relationships
    users_with_access = relationship(
        "User",
        secondary="user_store_access",
        back_populates="accessible_stores",
    )
    products = relationship("Product", back_populates="store", cascade="all, delete-orphan")
    batches = relationship("Batch", back_populates="store", cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="store")
    invitations = relationship("StoreInvitation", back_populates="store", cascade="all, delete-orphan")
