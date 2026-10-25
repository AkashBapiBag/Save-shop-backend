import json
import uuid
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.inventory import Product
from app.models.notification import NotificationChannel, NotificationEvent
from app.models.store import Store
from app.models.transaction import PaymentMethod, Transaction
from app.services.notification_service import NotificationService


def test_handle_google_trigger_dev_mode(client: TestClient):
    store_id = uuid.uuid4()
    payload = {
        "event": "PRODUCT_SYNC_TRIGGERED",
        "store_id": str(store_id),
        "data": {"sync_type": "full"},
    }

    # In dev mode, secret check is bypassed or accepted
    resp = client.post("/api/v1/notifications/google-trigger", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "notification_id" in data["data"]


def test_handle_google_trigger_production_mode(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "GOOGLE_TRIGGER_WEBHOOK_SECRET", "super-secret-trigger-key-999")

    payload = {"event": "INVENTORY_RECONCILE"}

    # 1. Missing or invalid secret -> 401 Unauthorized
    resp_invalid = client.post(
        "/api/v1/notifications/google-trigger",
        json=payload,
        headers={"X-Trigger-Secret": "wrong-secret"},
    )
    assert resp_invalid.status_code == 401
    assert resp_invalid.json()["error"]["code"] == "UNAUTHORIZED"

    # 2. Correct secret -> 200 OK
    resp_valid = client.post(
        "/api/v1/notifications/google-trigger",
        json=payload,
        headers={"X-Trigger-Secret": "super-secret-trigger-key-999"},
    )
    assert resp_valid.status_code == 200
    assert resp_valid.json()["success"] is True


def test_notification_service_low_stock_and_payment_triggers(db_session: Session):
    store_id = uuid.uuid4()
    store = Store(
        store_id=store_id,
        name=f"Notify Store {store_id.hex[:6]}",
        phone_number="+1000000000",
    )
    db_session.add(store)

    prod = Product(
        product_id=uuid.uuid4(),
        store_id=store_id,
        name="Basmati Rice Gold",
        selling_price=Decimal("120.00"),
        min_stock_alert_threshold=Decimal("10.000"),
        barcode="RICE-GOLD-01",
    )
    db_session.add(prod)
    db_session.commit()

    # 1. Test low stock alert dispatch
    log = NotificationService.trigger_low_stock_alert(
        db=db_session,
        store_id=store_id,
        product=prod,
        current_stock=4.5,
    )
    assert log.event_type == NotificationEvent.LOW_STOCK_ALERT.value
    assert log.channel == NotificationChannel.GOOGLE_TRIGGER.value
    assert "Basmati Rice Gold" in log.title
    payload_dict = json.loads(log.payload)
    assert payload_dict["current_stock"] == 4.5
    assert payload_dict["threshold"] == 10.0

    # 2. Test payment confirmation with phone (channel=WHATSAPP)
    tx_phone = Transaction(
        transaction_id=uuid.uuid4(),
        store_id=store_id,
        invoice_number="INV-NOTIF-01",
        customer_phone="+919876543210",
        subtotal=Decimal("250.00"),
        final_total=Decimal("250.00"),
        payment_method=PaymentMethod.UPI.value,
        payment_status="PAID",
    )
    db_session.add(tx_phone)
    db_session.commit()

    tx_log = NotificationService.trigger_payment_confirmation(db=db_session, transaction=tx_phone)
    assert tx_log.channel == NotificationChannel.WHATSAPP.value
    assert tx_log.recipient == "+919876543210"
    assert "INV-NOTIF-01" in tx_log.message

    # 3. Test payment confirmation with email only (channel=EMAIL)
    tx_email = Transaction(
        transaction_id=uuid.uuid4(),
        store_id=store_id,
        invoice_number="INV-NOTIF-02",
        customer_email="buyer@domain.com",
        subtotal=Decimal("100.00"),
        final_total=Decimal("100.00"),
        payment_method=PaymentMethod.CASH.value,
        payment_status="PAID",
    )
    db_session.add(tx_email)
    db_session.commit()

    tx_log_email = NotificationService.trigger_payment_confirmation(db=db_session, transaction=tx_email)
    assert tx_log_email.channel == NotificationChannel.EMAIL.value
    assert tx_log_email.recipient == "buyer@domain.com"

    # 4. Test payment confirmation without customer contact (channel=IN_APP)
    tx_anon = Transaction(
        transaction_id=uuid.uuid4(),
        store_id=store_id,
        invoice_number="INV-NOTIF-03",
        subtotal=Decimal("50.00"),
        final_total=Decimal("50.00"),
        payment_method=PaymentMethod.CASH.value,
        payment_status="PAID",
    )
    db_session.add(tx_anon)
    db_session.commit()

    tx_log_anon = NotificationService.trigger_payment_confirmation(db=db_session, transaction=tx_anon)
    assert tx_log_anon.channel == NotificationChannel.IN_APP.value
    assert tx_log_anon.recipient == "Store Terminal"


def test_list_notification_logs_endpoint(client: TestClient, admin_headers: dict):
    # Create store
    s_resp = client.post("/api/v1/stores/create", json={"name": "Log Store"}, headers=admin_headers)
    store_id = s_resp.json()["store_id"]
    headers = {**admin_headers, "X-Store-Id": store_id}

    # Trigger a google notification
    client.post(
        "/api/v1/notifications/google-trigger",
        json={"event": "TEST_EVENT", "store_id": store_id},
    )

    # Fetch logs
    resp = client.get("/api/v1/notifications/logs?limit=10", headers=headers)
    assert resp.status_code == 200
    logs = resp.json()
    assert len(logs) >= 1
    assert logs[0]["event_type"] == "TEST_EVENT"
    assert logs[0]["channel"] == "GOOGLE_TRIGGER"
