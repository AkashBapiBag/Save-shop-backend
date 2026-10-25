import base64
import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.transaction import Transaction


def test_create_store_admin(client: TestClient, admin_headers: dict):
    resp = client.post(
        "/api/v1/stores/create",
        json={
            "name": "Main Mega Store",
            "phone_number": "+1999888777",
            "address": "456 Market St, Cityville",
            "email": "contact@megastore.com",
        },
        headers=admin_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Main Mega Store"
    assert data["phone_number"] == "+1999888777"
    assert "store_id" in data


def test_create_store_forbidden_for_standard_user(client: TestClient, standard_user_headers: dict):
    resp = client.post(
        "/api/v1/stores/create",
        json={"name": "Unauthorized Store"},
        headers=standard_user_headers,
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_create_store_presave_constraint_with_existing_transactions(
    client: TestClient,
    admin_headers: dict,
    db_session: Session,
):
    """
    Validates Section 2.2 critical constraint:
    When attempting to create a new store, a pre-save check confirms zero existing linked data records.
    """
    conflicting_store_id = uuid.uuid4()

    # Artificially insert a transaction record linked to this id prior to store creation
    dummy_tx = Transaction(
        transaction_id=uuid.uuid4(),
        store_id=conflicting_store_id,
        invoice_number="INV-ORPHAN-001",
        subtotal=100.0,
        final_total=100.0,
        payment_method="CASH",
        payment_status="PAID",
    )
    db_session.add(dummy_tx)
    db_session.commit()

    # Attempt to create store with this conflicting ID
    resp = client.post(
        "/api/v1/stores/create",
        json={
            "store_id": str(conflicting_store_id),
            "name": "Conflicting Store",
        },
        headers=admin_headers,
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "STORE_CREATION_INTEGRITY_VIOLATION"


def test_store_signature_upload_and_retrieval(client: TestClient, admin_headers: dict):
    # 1. Create Store
    s_resp = client.post(
        "/api/v1/stores/create",
        json={"name": "Signature Test Store"},
        headers=admin_headers,
    )
    store_id = s_resp.json()["store_id"]

    # 2. Upload Signature
    dummy_sig_bytes = b"fake-png-binary-signature-data-bytes-12345"
    dummy_sig_b64 = base64.b64encode(dummy_sig_bytes).decode("utf-8")

    upload_resp = client.post(
        f"/api/v1/stores/{store_id}/signature",
        json={"signature_base64": dummy_sig_b64},
        headers=admin_headers,
    )
    assert upload_resp.status_code == 200
    assert upload_resp.json()["has_signature"] is True

    # 3. Retrieve Signature
    get_resp = client.get(f"/api/v1/stores/{store_id}/signature", headers=admin_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["signature_base64"] == dummy_sig_b64


def test_create_and_update_store_with_owner_logo_and_signature(client: TestClient, admin_headers: dict):
    dummy_logo_bytes = b"fake-square-logo-png-data"
    dummy_logo_b64 = base64.b64encode(dummy_logo_bytes).decode("utf-8")
    dummy_sig_bytes = b"fake-signature-png-data"
    dummy_sig_b64 = base64.b64encode(dummy_sig_bytes).decode("utf-8")

    # 1. Create with owner_name, logo_base64, and signature
    create_resp = client.post(
        "/api/v1/stores/create",
        json={
            "name": "Super Owner Store",
            "owner_name": "Jane Doe",
            "address": "123 High Street",
            "email": "jane@superstore.com",
            "phone_number": "+1234567890",
            "logo_base64": dummy_logo_b64,
            "authorized_signature_base64": dummy_sig_b64,
        },
        headers=admin_headers,
    )
    assert create_resp.status_code == 201
    created_data = create_resp.json()
    assert created_data["name"] == "Super Owner Store"
    assert created_data["owner_name"] == "Jane Doe"
    assert created_data["has_logo"] is True
    assert created_data["logo_base64"] == dummy_logo_b64
    assert created_data["has_signature"] is True
    assert created_data["authorized_signature_base64"] == dummy_sig_b64
    store_id = created_data["store_id"]

    # 2. Update store: change owner_name and update logo
    new_logo_b64 = base64.b64encode(b"updated-logo-data").decode("utf-8")
    update_resp = client.put(
        f"/api/v1/stores/{store_id}",
        json={
            "owner_name": "Jane Smith",
            "logo_base64": new_logo_b64,
        },
        headers=admin_headers,
    )
    assert update_resp.status_code == 200
    updated_data = update_resp.json()
    assert updated_data["owner_name"] == "Jane Smith"
    assert updated_data["logo_base64"] == new_logo_b64
    assert updated_data["has_signature"] is True


def test_indian_states_list_and_store_state_selection(client, admin_headers):
    # 1. Test GET /api/v1/stores/states endpoint
    states_resp = client.get("/api/v1/stores/states")
    assert states_resp.status_code == 200
    states = states_resp.json()
    assert len(states) >= 36
    wb = next((s for s in states if s["code"] == "19"), None)
    assert wb is not None
    assert wb["name"] == "West Bengal"
    assert wb["display_name"] == "19-West Bengal"

    mh = next((s for s in states if s["code"] == "27"), None)
    assert mh is not None
    assert mh["name"] == "Maharashtra"
    assert mh["display_name"] == "27-Maharashtra"

    # 2. Test Store Creation with selected state
    create_resp = client.post(
        "/api/v1/stores/create",
        json={
            "name": "Mumbai Megamart",
            "state": "27-Maharashtra",
            "address": "Bandra West, Mumbai",
            "phone_number": "+91 9876543210",
        },
        headers=admin_headers,
    )
    assert create_resp.status_code == 201
    store = create_resp.json()
    assert store["name"] == "Mumbai Megamart"
    assert store["state"] == "27-Maharashtra"
    store_id = store["store_id"]

    # 3. Test Store Update to change state
    update_resp = client.put(
        f"/api/v1/stores/{store_id}",
        json={"state": "29-Karnataka"},
        headers=admin_headers,
    )
    assert update_resp.status_code == 200
    updated_store = update_resp.json()
    assert updated_store["state"] == "29-Karnataka"
