import base64
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.exceptions import (
    DuplicateEntityException,
    EntityNotFoundException,
)
from app.models.inventory import Batch, Product, UnitEnum
from app.models.store import Store
from app.models.user import User, UserRole
from app.schemas.auth import LoginRequest
from app.schemas.inventory import ProductUpdate
from app.schemas.store import StoreCreate, StoreUpdate
from app.services.auth_service import AuthService
from app.services.inventory_service import InventoryService
from app.services.store_service import StoreService

# =============================================================================
# 1. POS OFFLINE SYNC & FINANCIAL EDGE CASES
# =============================================================================


def test_pos_offline_sync_batch_with_idempotency_and_failures(client: TestClient, admin_headers: dict):
    # Setup store and product
    s_resp = client.post("/api/v1/stores/create", json={"name": f"Sync Store {uuid.uuid4().hex[:6]}"}, headers=admin_headers)
    store_id = s_resp.json()["store_id"]
    headers = {**admin_headers, "X-Store-Id": store_id}
    today = date.today()

    p_resp = client.post(
        "/api/v1/inventory/products",
        json={"name": "Energy Bar", "category": "Snacks", "default_unit": "PACKET", "selling_price": "20.00"},
        headers=headers,
    )
    prod_id = p_resp.json()["product_id"]

    # Inward 10 packets
    client.post(
        "/api/v1/inventory/receive/single",
        json={
            "product_id": prod_id,
            "batch_identifier": "LOT-BAR-01",
            "quantity": "10.000",
            "purchase_date": today.isoformat(),
            "expiry_date": (today + timedelta(days=90)).isoformat(),
        },
        headers=headers,
    )

    offline_id_1 = f"offline-tx-{uuid.uuid4().hex[:8]}"
    offline_id_2 = f"offline-tx-{uuid.uuid4().hex[:8]}"

    sync_payload = {
        "store_id": store_id,
        "transactions": [
            # Tx 1: Valid sale of 2 bars
            {
                "store_id": store_id,
                "client_offline_id": offline_id_1,
                "items": [{"product_id": prod_id, "quantity": "2.000"}],
                "payment_method": "CASH",
            },
            # Tx 2: Excess stock request (attempt to buy 50 bars when only 8 remain)
            {
                "store_id": store_id,
                "client_offline_id": offline_id_2,
                "items": [{"product_id": prod_id, "quantity": "50.000"}],
                "payment_method": "CASH",
            },
        ],
    }

    # First sync run
    sync_resp = client.post("/api/v1/billing/sync", json=sync_payload, headers=headers)
    assert sync_resp.status_code == 200
    res = sync_resp.json()
    assert res["total_received"] == 2
    assert res["synced_count"] == 1
    assert res["failed_count"] == 1

    tx1_res = next(r for r in res["results"] if r["client_offline_id"] == offline_id_1)
    assert tx1_res["status"] == "synced"
    assert tx1_res["invoice_number"] is not None

    tx2_res = next(r for r in res["results"] if r["client_offline_id"] == offline_id_2)
    assert tx2_res["status"] == "failed_insufficient_stock"

    # Second sync run with Tx 1 repeated (idempotency verification)
    repeat_payload = {
        "store_id": store_id,
        "transactions": [
            {
                "store_id": store_id,
                "client_offline_id": offline_id_1,
                "items": [{"product_id": prod_id, "quantity": "2.000"}],
                "payment_method": "CASH",
            }
        ],
    }
    repeat_resp = client.post("/api/v1/billing/sync", json=repeat_payload, headers=headers)
    assert repeat_resp.status_code == 200
    rep_res = repeat_resp.json()
    assert rep_res["already_synced_count"] == 1
    assert rep_res["results"][0]["status"] == "already_synced"
    assert rep_res["results"][0]["invoice_number"] == tx1_res["invoice_number"]


def test_pos_received_amount_greater_than_total(client: TestClient, admin_headers: dict):
    # Create store & product
    s_resp = client.post("/api/v1/stores/create", json={"name": f"Cash Store {uuid.uuid4().hex[:6]}"}, headers=admin_headers)
    store_id = s_resp.json()["store_id"]
    headers = {**admin_headers, "X-Store-Id": store_id}
    today = date.today()

    p_resp = client.post(
        "/api/v1/inventory/products",
        json={"name": "Pen", "category": "Stationery", "default_unit": "PIECE", "selling_price": "15.00"},
        headers=headers,
    )
    prod_id = p_resp.json()["product_id"]

    client.post(
        "/api/v1/inventory/receive/single",
        json={
            "product_id": prod_id,
            "batch_identifier": "LOT-PEN-01",
            "quantity": "20.000",
            "purchase_date": today.isoformat(),
            "expiry_date": (today + timedelta(days=365)).isoformat(),
        },
        headers=headers,
    )

    # Buy 2 pens = ₹30.00. Customer gives ₹50.00 note.
    # Received: 50.00, Balance should be 0.00 (since full bill is settled), status = PAID.
    tx_resp = client.post(
        "/api/v1/billing/checkout",
        json={
            "items": [{"product_id": prod_id, "quantity": "2.000"}],
            "received_amount": "50.00",
            "payment_method": "CASH",
        },
        headers=headers,
    )
    assert tx_resp.status_code == 201
    tx = tx_resp.json()
    assert float(tx["final_total"]) == 30.00
    assert float(tx["received_amount"]) == 50.00
    assert float(tx["balance_amount"]) == 0.00
    assert tx["payment_status"] == "PAID"


def test_pos_checkout_with_inactive_product_rejected(client: TestClient, admin_headers: dict):
    s_resp = client.post("/api/v1/stores/create", json={"name": "Inactive Prod Store"}, headers=admin_headers)
    store_id = s_resp.json()["store_id"]
    headers = {**admin_headers, "X-Store-Id": store_id}

    p = client.post(
        "/api/v1/inventory/products",
        json={"name": "Discontinued Soda", "selling_price": "25.00"},
        headers=headers,
    ).json()
    prod_id = p["product_id"]

    # Deactivate product
    client.put(f"/api/v1/inventory/products/{prod_id}", json={"is_active": False}, headers=headers)

    # Attempt to sell
    resp = client.post(
        "/api/v1/billing/checkout",
        json={"items": [{"product_id": prod_id, "quantity": "1.000"}]},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "currently inactive and cannot be sold" in resp.json()["error"]["message"]


def test_pos_date_filtering_options(client: TestClient, admin_headers: dict):
    s_resp = client.post("/api/v1/stores/create", json={"name": "Date Filter Store"}, headers=admin_headers)
    store_id = s_resp.json()["store_id"]
    headers = {**admin_headers, "X-Store-Id": store_id}
    today = date.today()

    p = client.post(
        "/api/v1/inventory/products",
        json={"name": "Cookie", "selling_price": "10.00"},
        headers=headers,
    ).json()

    client.post(
        "/api/v1/inventory/receive/single",
        json={
            "product_id": p["product_id"],
            "batch_identifier": "LOT-CK-1",
            "quantity": "50.000",
            "purchase_date": today.isoformat(),
            "expiry_date": (today + timedelta(days=60)).isoformat(),
        },
        headers=headers,
    )

    # Perform transaction
    client.post(
        "/api/v1/billing/checkout",
        json={"items": [{"product_id": p["product_id"], "quantity": "1.000"}]},
        headers=headers,
    )

    # Test date filters: 'yesterday', 'this_week', 'this_month', and custom start_date/end_date
    yesterday_res = client.get("/api/v1/billing/transactions?date_filter=yesterday", headers=headers).json()
    assert len(yesterday_res) == 0

    week_res = client.get("/api/v1/billing/transactions?date_filter=this_week", headers=headers).json()
    assert len(week_res) >= 1

    month_res = client.get("/api/v1/billing/transactions?date_filter=this_month", headers=headers).json()
    assert len(month_res) >= 1

    today_utc = datetime.now(timezone.utc).date()
    custom_res = client.get(
        f"/api/v1/billing/transactions?start_date={today_utc.isoformat()}&end_date={today_utc.isoformat()}",
        headers=headers,
    ).json()
    assert len(custom_res) >= 1


# =============================================================================
# 2. STORE SERVICE EDGE CASES
# =============================================================================


def test_store_service_duplicate_name_error(db_session: Session):
    admin = User(user_id=uuid.uuid4(), email="adm-dup@domain.com", name="Admin User", role=UserRole.ADMIN.value, is_active=True)
    db_session.add(admin)
    db_session.commit()

    s1 = StoreCreate(name="Unique MegaMart 101", phone_number="+111")
    StoreService.create_store(db_session, s1, admin)

    s2 = StoreCreate(name="Unique MegaMart 101", phone_number="+222")
    with pytest.raises(DuplicateEntityException):
        StoreService.create_store(db_session, s2, admin)


def test_store_service_base64_data_uri_handling(db_session: Session):
    admin = User(user_id=uuid.uuid4(), email="adm-b64@domain.com", name="Admin User", role=UserRole.ADMIN.value, is_active=True)
    db_session.add(admin)
    db_session.commit()

    raw_logo_bytes = b"sample-logo-bytes-555"
    raw_sig_bytes = b"sample-sig-bytes-777"
    logo_data_uri = "data:image/png;base64," + base64.b64encode(raw_logo_bytes).decode("utf-8")
    sig_data_uri = "data:image/png;base64," + base64.b64encode(raw_sig_bytes).decode("utf-8")

    store = StoreService.create_store(
        db_session,
        StoreCreate(
            name=f"DataUri Store {uuid.uuid4().hex[:6]}",
            logo_base64=logo_data_uri,
            authorized_signature_base64=sig_data_uri,
        ),
        admin,
    )

    assert store.logo_data == raw_logo_bytes
    assert store.authorized_signature_data == raw_sig_bytes
    assert StoreService.get_logo_base64(store) == base64.b64encode(raw_logo_bytes).decode("utf-8")
    assert StoreService.get_signature_base64(store) == base64.b64encode(raw_sig_bytes).decode("utf-8")


def test_store_service_get_and_update_nonexistent_raises(db_session: Session):
    random_id = uuid.uuid4()
    admin = User(user_id=uuid.uuid4(), email="adm-ne@domain.com", role=UserRole.ADMIN.value, is_active=True)

    with pytest.raises(EntityNotFoundException):
        StoreService.get_store_by_id(db_session, random_id)

    with pytest.raises(EntityNotFoundException):
        StoreService.update_store(db_session, random_id, StoreUpdate(name="New Name"), admin)


# =============================================================================
# 3. INVENTORY SERVICE EDGE CASES
# =============================================================================


def test_inventory_service_update_all_product_fields(db_session: Session):
    store_id = uuid.uuid4()
    store = Store(store_id=store_id, name="Inv Service Store")
    db_session.add(store)

    prod = Product(
        product_id=uuid.uuid4(),
        store_id=store_id,
        name="Initial Name",
        description="Initial Desc",
        category="Cat A",
        default_unit="KG",
        selling_price=Decimal("100.00"),
        cost_price=Decimal("60.00"),
        min_stock_alert_threshold=Decimal("5.000"),
        barcode="BAR-111",
        is_active=True,
    )
    db_session.add(prod)
    db_session.commit()

    # Update all fields
    update_data = ProductUpdate(
        name="Updated Name",
        description="Updated Desc",
        category="Cat B",
        default_unit=UnitEnum.GRAM,
        selling_price=Decimal("150.00"),
        cost_price=Decimal("90.00"),
        min_stock_alert_threshold=Decimal("8.000"),
        barcode="BAR-222",
        is_active=False,
    )
    updated = InventoryService.update_product(db_session, prod.product_id, update_data, store_id)

    assert updated.name == "Updated Name"
    assert updated.description == "Updated Desc"
    assert updated.category == "Cat B"
    assert updated.default_unit == UnitEnum.GRAM.value
    assert updated.selling_price == Decimal("150.00")
    assert updated.cost_price == Decimal("90.00")
    assert updated.min_stock_alert_threshold == Decimal("8.000")
    assert updated.barcode == "BAR-222"
    assert updated.is_active is False


def test_inventory_service_batch_response_expiry_attributes():
    today = date.today()
    batch_active = Batch(
        batch_id=uuid.uuid4(),
        product_id=uuid.uuid4(),
        store_id=uuid.uuid4(),
        batch_identifier="LOT-EXP-1",
        initial_quantity=Decimal("10.000"),
        current_quantity=Decimal("10.000"),
        purchase_price=Decimal("50.00"),
        purchase_date=today,
        expiry_date=today + timedelta(days=20),
        created_at=today,
    )
    res_active = InventoryService.to_batch_response(batch_active)
    assert res_active.is_expired is False
    assert res_active.days_to_expiry == 20

    batch_expired = Batch(
        batch_id=uuid.uuid4(),
        product_id=uuid.uuid4(),
        store_id=uuid.uuid4(),
        batch_identifier="LOT-EXP-2",
        initial_quantity=Decimal("5.000"),
        current_quantity=Decimal("5.000"),
        purchase_price=Decimal("30.00"),
        purchase_date=today - timedelta(days=60),
        expiry_date=today - timedelta(days=1),
        created_at=today,
    )
    res_expired = InventoryService.to_batch_response(batch_expired)
    assert res_expired.is_expired is True
    assert res_expired.days_to_expiry < 0


# =============================================================================
# 4. AUTH SERVICE & DASHBOARD EDGE CASES
# =============================================================================


def test_auth_service_dev_login_and_store_assignment(db_session: Session):
    # Dev login creates user
    email = f"clerk-{uuid.uuid4().hex[:6]}@domain.com"
    req = LoginRequest(email=email, name="New Clerk", role=UserRole.USER)
    token_resp = AuthService.dev_login(db_session, req)
    assert token_resp.access_token is not None
    assert token_resp.user.email == email
    user_id = token_resp.user.user_id

    # Create Store
    store = Store(store_id=uuid.uuid4(), name=f"Auth Store {uuid.uuid4().hex[:6]}")
    db_session.add(store)
    db_session.commit()

    # Assign user to store
    assigned = AuthService.assign_user_to_store(db_session, user_id=user_id, store_id=store.store_id)
    assert assigned is True

    # Re-assigning is idempotent
    assert AuthService.assign_user_to_store(db_session, user_id=user_id, store_id=store.store_id) is True


def test_dashboard_service_with_empty_store(db_session: Session):
    store = Store(store_id=uuid.uuid4(), name=f"Empty Store {uuid.uuid4().hex[:6]}")
    db_session.add(store)
    db_session.commit()

    from app.services.dashboard_service import DashboardService

    overview = DashboardService.get_overview(db_session, store.store_id)
    assert overview.today_transaction_count == 0
    assert overview.today_revenue == Decimal("0.00")
    assert overview.total_active_products == 0

    health = DashboardService.get_stock_health(db_session, store.store_id)
    assert health.total_critical_batches == 0

    velocity = DashboardService.get_sales_velocity(db_session, store.store_id, period_days=7)
    assert len(velocity.top_selling_items) == 0

    status_resp = DashboardService.get_inventory_status(db_session, store.store_id)
    assert status_resp.total_products == 0


# =============================================================================
# 5. MAIN APPLICATION HEALTH AND EXCEPTION HANDLERS
# =============================================================================


def test_root_and_health_endpoints(client: TestClient):
    # Root
    root_resp = client.get("/")
    assert root_resp.status_code == 200
    assert root_resp.json()["status"] == "operational"

    # Health
    health_resp = client.get("/health")
    assert health_resp.status_code == 200


def test_stores_logo_endpoints_and_listing(client: TestClient, admin_headers: dict, standard_user_headers: dict):
    # Create Store
    s_resp = client.post("/api/v1/stores/create", json={"name": f"Logo Store {uuid.uuid4().hex[:6]}"}, headers=admin_headers)
    store_id = s_resp.json()["store_id"]

    # 1. Admin lists stores
    admin_stores = client.get("/api/v1/stores", headers=admin_headers).json()
    assert len(admin_stores) >= 1
    assert any(s["store_id"] == store_id for s in admin_stores)

    # 2. Get store by ID
    store_detail = client.get(f"/api/v1/stores/{store_id}", headers=admin_headers).json()
    assert store_detail["store_id"] == store_id

    # 3. Update logo via PUT /stores/{store_id}
    fake_logo = base64.b64encode(b"new-logo-content").decode("utf-8")
    up_logo_resp = client.put(
        f"/api/v1/stores/{store_id}",
        json={"logo_base64": fake_logo},
        headers=admin_headers,
    )
    assert up_logo_resp.status_code == 200
    assert up_logo_resp.json()["has_logo"] is True
    assert up_logo_resp.json()["logo_base64"] == fake_logo

    # 4. Standard user forbidden to update store
    std_update_fail = client.put(
        f"/api/v1/stores/{store_id}",
        json={"name": "Hacked Name"},
        headers=standard_user_headers,
    )
    assert std_update_fail.status_code == 403

    # 5. Standard user forbidden to upload signature
    std_sig_fail = client.post(
        f"/api/v1/stores/{store_id}/signature",
        json={"signature_base64": fake_logo},
        headers=standard_user_headers,
    )
    assert std_sig_fail.status_code == 403


def test_cross_tenant_store_id_in_payload_rejection(client: TestClient, admin_headers: dict):
    s1 = client.post("/api/v1/stores/create", json={"name": "Tenant One"}, headers=admin_headers).json()["store_id"]
    s2 = client.post("/api/v1/stores/create", json={"name": "Tenant Two"}, headers=admin_headers).json()["store_id"]
    headers1 = {**admin_headers, "X-Store-Id": s1}

    # 1. Mismatched store_id in receive single
    p1 = client.post(
        "/api/v1/inventory/products",
        json={"name": "T1 Prod", "selling_price": "10.00"},
        headers=headers1,
    ).json()["product_id"]

    resp1 = client.post(
        "/api/v1/inventory/receive/single",
        json={
            "store_id": s2,
            "product_id": p1,
            "batch_identifier": "B1",
            "quantity": "5.000",
            "expiry_date": (date.today() + timedelta(days=30)).isoformat(),
        },
        headers=headers1,
    )
    assert resp1.status_code == 403

    # 2. Mismatched store_id in receive bulk
    resp2 = client.post(
        "/api/v1/inventory/receive/bulk",
        json={
            "store_id": s2,
            "batches": [
                {
                    "product_id": p1,
                    "batch_identifier": "B1",
                    "quantity": "5.000",
                    "expiry_date": (date.today() + timedelta(days=30)).isoformat(),
                }
            ],
        },
        headers=headers1,
    )
    assert resp2.status_code == 403

    # 3. Mismatched store_id in billing sync
    resp3 = client.post(
        "/api/v1/billing/sync",
        json={
            "store_id": s2,
            "transactions": [
                {
                    "store_id": s2,
                    "items": [{"product_id": p1, "quantity": "1.000"}],
                }
            ],
        },
        headers=headers1,
    )
    assert resp3.status_code == 403


def test_auth_service_edge_cases(db_session: Session):
    # 1. Token without email uses fallback
    fake_token_data = {"sub": "google-oauth2|12345", "name": "Google User"}
    from app.core.security import create_access_token

    token = create_access_token(fake_token_data)
    user = AuthService.get_or_create_user_from_token(db_session, token)
    assert user.auth0_sub == "google-oauth2|12345"
    assert "@saveshop.local" in user.email

    # 2. Assign non-existent user / store raises EntityNotFoundException
    with pytest.raises(EntityNotFoundException):
        AuthService.assign_user_to_store(db_session, user_id=uuid.uuid4(), store_id=uuid.uuid4())

    with pytest.raises(EntityNotFoundException):
        AuthService.assign_user_to_store(db_session, user_id=user.user_id, store_id=uuid.uuid4())

    # 3. Switch to non-existent store raises EntityNotFoundException
    with pytest.raises(EntityNotFoundException):
        AuthService.switch_store(db_session, user, uuid.uuid4())


def test_dashboard_service_with_expired_and_warning_batches(db_session: Session):
    store = Store(store_id=uuid.uuid4(), name=f"Expiry Store {uuid.uuid4().hex[:6]}")
    db_session.add(store)

    prod = Product(
        product_id=uuid.uuid4(),
        store_id=store.store_id,
        name="Expired Milk",
        selling_price=Decimal("20.00"),
    )
    db_session.add(prod)

    today = date.today()

    # Expired batch
    b_exp = Batch(
        batch_id=uuid.uuid4(),
        product_id=prod.product_id,
        store_id=store.store_id,
        batch_identifier="LOT-EXPIRED",
        initial_quantity=Decimal("10.000"),
        current_quantity=Decimal("5.000"),
        purchase_date=today - timedelta(days=40),
        expiry_date=today - timedelta(days=5),
    )
    # Warning 60 days batch
    b_warn = Batch(
        batch_id=uuid.uuid4(),
        product_id=prod.product_id,
        store_id=store.store_id,
        batch_identifier="LOT-WARN-60",
        initial_quantity=Decimal("20.000"),
        current_quantity=Decimal("20.000"),
        purchase_date=today,
        expiry_date=today + timedelta(days=45),
    )
    db_session.add_all([b_exp, b_warn])
    db_session.commit()

    from app.services.dashboard_service import DashboardService

    health = DashboardService.get_stock_health(db_session, store.store_id)
    assert health.expired_batches_count >= 1
    assert health.expiring_60_days_count >= 1

    inv_status = DashboardService.get_inventory_status(db_session, store.store_id)
    assert inv_status.expiring_batches_summary["expired"] >= 1
    assert inv_status.expiring_batches_summary["within_60_days"] >= 1
