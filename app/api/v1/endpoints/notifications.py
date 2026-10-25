import uuid

from fastapi import APIRouter, Body, Depends, Header
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_active_user, get_current_store_context
from app.core.exceptions import UnauthorizedException
from app.models.notification import NotificationLog
from app.models.user import User
from app.schemas.common import APIResponse

router = APIRouter(prefix="/notifications", tags=["Notifications & Google Trigger Integration"])


@router.post(
    "/google-trigger",
    response_model=APIResponse[dict],
    summary="Webhook for Google Trigger Mechanism",
)
def handle_google_trigger(
    payload: dict = Body(...),
    x_trigger_secret: str | None = Header(None, alias="X-Trigger-Secret"),
    db: Session = Depends(get_db),
):
    """
    Asynchronous receiver for Google Trigger Mechanism (Cloud Tasks / Cloud Functions / PubSub).
    Authenticates via webhook secret and logs or executes the trigger event.
    """
    if x_trigger_secret != settings.GOOGLE_TRIGGER_WEBHOOK_SECRET and settings.ENVIRONMENT == "production":
        raise UnauthorizedException("Invalid Google Trigger webhook secret")

    event_type = payload.get("event", "GOOGLE_TRIGGER_RECEIVED")
    store_id_str = payload.get("store_id")
    store_id = uuid.UUID(store_id_str) if store_id_str else None

    log = NotificationLog(
        notification_id=uuid.uuid4(),
        store_id=store_id,
        event_type=event_type,
        channel="GOOGLE_TRIGGER",
        title=f"Google Trigger Executed: {event_type}",
        message=f"Received external Google Trigger callback for store {store_id or 'Global'}",
        payload=str(payload),
        status="PROCESSED",
    )
    db.add(log)
    db.commit()

    return APIResponse(
        message="Google Trigger event processed successfully.",
        data={"notification_id": str(log.notification_id)},
    )


@router.get(
    "/logs",
    summary="List Recent Notification Logs for Active Store",
)
def list_notification_logs(
    limit: int = 50,
    store_id: uuid.UUID = Depends(get_current_store_context),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Returns recent dispatch logs (Low Stock alerts, payment confirmations, trigger logs).
    """
    logs = (
        db.query(NotificationLog)
        .filter(NotificationLog.store_id == store_id)
        .order_by(NotificationLog.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "notification_id": str(log.notification_id),
            "event_type": log.event_type,
            "channel": log.channel,
            "recipient": log.recipient,
            "title": log.title,
            "message": log.message,
            "status": log.status,
            "created_at": log.created_at,
        }
        for log in logs
    ]
