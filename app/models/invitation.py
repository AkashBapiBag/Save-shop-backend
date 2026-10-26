import uuid

from sqlalchemy import Column, ForeignKey, Index, String
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.models.base import GUID, TimestampMixin


class StoreInvitation(Base, TimestampMixin):
    __tablename__ = "store_invitations"

    invitation_id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    store_id = Column(GUID(), ForeignKey("stores.store_id", ondelete="CASCADE"), nullable=False, index=True)
    email = Column(String(255), nullable=False, index=True)
    role = Column(String(50), default="user", nullable=False)
    status = Column(String(50), default="pending", nullable=False)  # pending, accepted, revoked
    invited_by_id = Column(GUID(), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)

    # Relationships
    store = relationship("Store", back_populates="invitations")
    invited_by = relationship("User", foreign_keys=[invited_by_id])

    __table_args__ = (
        Index("uq_store_invitations_store_email_pending", "store_id", "email"),
    )
