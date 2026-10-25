import uuid
from enum import Enum

from sqlalchemy import Column, ForeignKey, String, Text

from app.core.database import Base
from app.models.base import GUID, TimestampMixin


class NotificationEvent(str, Enum):
    LOW_STOCK_ALERT = "LOW_STOCK_ALERT"
    EXPIRY_WARNING = "EXPIRY_WARNING"
    PAYMENT_CONFIRMATION = "PAYMENT_CONFIRMATION"
    GOOGLE_TRIGGER_RECEIVED = "GOOGLE_TRIGGER_RECEIVED"


class NotificationChannel(str, Enum):
    GOOGLE_TRIGGER = "GOOGLE_TRIGGER"
    WHATSAPP = "WHATSAPP"
    EMAIL = "EMAIL"
    IN_APP = "IN_APP"


class NotificationLog(Base, TimestampMixin):
    __tablename__ = "notification_logs"

    notification_id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    store_id = Column(GUID(), ForeignKey("stores.store_id", ondelete="CASCADE"), nullable=True)
    event_type = Column(String(50), nullable=False)
    channel = Column(String(50), nullable=False)
    recipient = Column(String(255), nullable=True)
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    payload = Column(Text, nullable=True)
    status = Column(String(50), default="SENT", nullable=False)
    error_message = Column(Text, nullable=True)
