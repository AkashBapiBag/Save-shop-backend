import json
import logging
import uuid

from sqlalchemy.orm import Session

from app.models.inventory import Product
from app.models.notification import NotificationChannel, NotificationEvent, NotificationLog
from app.models.transaction import Transaction

logger = logging.getLogger("saveshop.notifications")


class NotificationService:
    @staticmethod
    def trigger_low_stock_alert(
        db: Session,
        store_id: uuid.UUID,
        product: Product,
        current_stock: float,
    ) -> NotificationLog:
        """
        Dispatches low stock alert event via Google Trigger mechanism / In-App notification log.
        """
        title = f"Low Stock Warning: {product.name}"
        message = (
            f"Product '{product.name}' (SKU: {product.barcode or 'N/A'}) has dropped to {current_stock} "
            f"{product.default_unit}. The configured alert threshold is {product.min_stock_alert_threshold}."
        )
        payload = {
            "event": NotificationEvent.LOW_STOCK_ALERT.value,
            "product_id": str(product.product_id),
            "product_name": product.name,
            "store_id": str(store_id),
            "current_stock": float(current_stock),
            "threshold": float(product.min_stock_alert_threshold),
        }

        log = NotificationLog(
            notification_id=uuid.uuid4(),
            store_id=store_id,
            event_type=NotificationEvent.LOW_STOCK_ALERT.value,
            channel=NotificationChannel.GOOGLE_TRIGGER.value,
            title=title,
            message=message,
            payload=json.dumps(payload),
            status="SENT",
        )
        db.add(log)
        # Note: caller will commit within the outer transaction or separate session
        logger.info(f"[LOW_STOCK_ALERT] {message}")
        return log

    @staticmethod
    def trigger_payment_confirmation(
        db: Session,
        transaction: Transaction,
    ) -> NotificationLog:
        """
        Triggers payment confirmation / invoice generation notification.
        """
        recipient = transaction.customer_phone or transaction.customer_email or "Store Terminal"
        channel = (
            NotificationChannel.WHATSAPP.value
            if transaction.customer_phone
            else (NotificationChannel.EMAIL.value if transaction.customer_email else NotificationChannel.IN_APP.value)
        )
        title = f"Invoice #{transaction.invoice_number} Generated"
        message = (
            f"Thank you for shopping! Transaction #{transaction.invoice_number} "
            f"for amount ${float(transaction.final_total):.2f} via {transaction.payment_method} has been finalized."
        )
        payload = {
            "event": NotificationEvent.PAYMENT_CONFIRMATION.value,
            "invoice_number": transaction.invoice_number,
            "transaction_id": str(transaction.transaction_id),
            "store_id": str(transaction.store_id),
            "final_total": float(transaction.final_total),
            "payment_method": transaction.payment_method,
        }

        log = NotificationLog(
            notification_id=uuid.uuid4(),
            store_id=transaction.store_id,
            event_type=NotificationEvent.PAYMENT_CONFIRMATION.value,
            channel=channel,
            recipient=recipient,
            title=title,
            message=message,
            payload=json.dumps(payload),
            status="SENT",
        )
        db.add(log)
        logger.info(f"[PAYMENT_CONFIRMATION] Invoice {transaction.invoice_number} for store {transaction.store_id}")
        return log
