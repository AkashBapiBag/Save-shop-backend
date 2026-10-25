import uuid
from enum import Enum

from sqlalchemy import Boolean, Column, ForeignKey, String, Table
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.models.base import GUID, TimestampMixin


class UserRole(str, Enum):
    ADMIN = "admin"
    USER = "user"


# Many-to-many relationship linking users to authorized stores
user_store_access = Table(
    "user_store_access",
    Base.metadata,
    Column("user_id", GUID(), ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True),
    Column("store_id", GUID(), ForeignKey("stores.store_id", ondelete="CASCADE"), primary_key=True),
)


class User(Base, TimestampMixin):
    __tablename__ = "users"

    user_id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    auth0_sub = Column(String(255), unique=True, index=True, nullable=True)
    google_sub = Column(String(255), unique=True, index=True, nullable=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False)
    role = Column(String(50), default=UserRole.USER.value, nullable=False)
    picture_url = Column(String(500), nullable=True)
    current_store_id = Column(GUID(), ForeignKey("stores.store_id", ondelete="SET NULL"), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    # Relationships
    accessible_stores = relationship(
        "Store",
        secondary=user_store_access,
        back_populates="users_with_access",
    )
    current_store = relationship(
        "Store",
        foreign_keys=[current_store_id],
        post_update=True,
    )
    transactions = relationship("Transaction", back_populates="cashier")

    def is_admin(self) -> bool:
        return self.role.lower() == UserRole.ADMIN.value
