import uuid
from datetime import date, timedelta

from fastapi.testclient import TestClient


def test_multi_tenant_logical_separation(client: TestClient, admin_headers: dict):
    """
    Comprehensive Multi-Tenant Logical Separation Test:
    Validates that:
    1. Each store is an isolated tenant.
    2. Products & Stock do not leak across stores.
    3. Categories are strictly tenant-scoped.
    4. Batches & Inventory levels are isolated.
    5. Billing & Transactions cannot be seen by other tenants.
    6. Non-admin users cannot access other store data.
    7. Cross-tenant payload tampering is rejected.
    """
    # -------------------------------------------------------------------------
    # 1. Create Tenant A and Tenant B
    # -------------------------------------------------------------------------
    store_a_resp = client.post(
        "/api/v1/stores/create",
        json={"name": f"Tenant Alpha {uuid.uuid4().hex[:6]}", "phone_number": "111-111-1111"},
        headers=admin_headers,
    )
    assert store_a_resp.status_code == 201
    store_a_id = store_a_resp.json()["store_id"]
    headers_a = {**admin_headers, "X-Store-Id": store_a_id}

    store_b_resp = client.post(
        "/api/v1/stores/create",
        json={"name": f"Tenant Beta {uuid.uuid4().hex[:6]}", "phone_number": "222-222-2222"},
        headers=admin_headers,
    )
    assert store_b_resp.status_code == 201
    store_b_id = store_b_resp.json()["store_id"]
    headers_b = {**admin_headers, "X-Store-Id": store_b_id}

    # -------------------------------------------------------------------------
    # 2. Product Creation & Isolation
    # -------------------------------------------------------------------------
    # Create product in Tenant A (Category: Dairy)
    p_a = client.post(
        "/api/v1/inventory/products",
        json={
            "name": "Alpha Cow Milk",
            "category": "Dairy",
            "default_unit": "LITER",
            "selling_price": "5.00",
            "barcode": "MILK-ALPHA-01",
        },
        headers=headers_a,
    ).json()

    # Create product in Tenant B (Category: Electronics)
    client.post(
        "/api/v1/inventory/products",
        json={
            "name": "Beta USB Cable",
            "category": "Electronics",
            "default_unit": "PIECE",
            "selling_price": "12.00",
            "barcode": "CABLE-BETA-01",
        },
        headers=headers_b,
    )

    # Tenant A list products -> must only have Alpha Cow Milk
    list_a = client.get("/api/v1/inventory/products", headers=headers_a).json()
    assert len(list_a) == 1
    assert list_a[0]["name"] == "Alpha Cow Milk"

    # Tenant B list products -> must only have Beta USB Cable
    list_b = client.get("/api/v1/inventory/products", headers=headers_b).json()
    assert len(list_b) == 1
    assert list_b[0]["name"] == "Beta USB Cable"

    # Cross-tenant product access by ID must return 404
    get_cross_resp = client.get(f"/api/v1/inventory/products/{p_a['product_id']}", headers=headers_b)
    assert get_cross_resp.status_code == 404

    # -------------------------------------------------------------------------
    # 3. Category Logical Separation
    # -------------------------------------------------------------------------
    cats_a = client.get("/api/v1/inventory/categories", headers=headers_a).json()
    assert len(cats_a) == 1
    assert cats_a[0]["name"] == "Dairy"
    assert cats_a[0]["count"] == 1

    cats_b = client.get("/api/v1/inventory/categories", headers=headers_b).json()
    assert len(cats_b) == 1
    assert cats_b[0]["name"] == "Electronics"
    assert cats_b[0]["count"] == 1

    # -------------------------------------------------------------------------
    # 4. Stock & Batch Isolation
    # -------------------------------------------------------------------------
    today = date.today()
    exp_date = today + timedelta(days=30)

    # Inward stock for Alpha Milk in Tenant A
    client.post(
        "/api/v1/inventory/receive/single",
        json={
            "product_id": p_a["product_id"],
            "batch_identifier": "BATCH-MILK-01",
            "quantity": "50.000",
            "expiry_date": exp_date.isoformat(),
            "purchase_date": today.isoformat(),
        },
        headers=headers_a,
    )

    # Check Tenant A stock is 50
    prod_a_updated = client.get(f"/api/v1/inventory/products/{p_a['product_id']}", headers=headers_a).json()
    assert float(prod_a_updated["total_current_stock"]) == 50.0

    # Inward stock for Alpha Milk using Tenant B context -> must fail with 404
    cross_receive = client.post(
        "/api/v1/inventory/receive/single",
        json={
            "product_id": p_a["product_id"],
            "batch_identifier": "BATCH-HACK-01",
            "quantity": "10.000",
            "expiry_date": exp_date.isoformat(),
            "purchase_date": today.isoformat(),
        },
        headers=headers_b,
    )
    assert cross_receive.status_code == 404

    # Tenant B batches query must NOT include Tenant A batches
    batches_b = client.get("/api/v1/inventory/batches", headers=headers_b).json()
    assert len(batches_b) == 0

    # -------------------------------------------------------------------------
    # 5. Billing & Transaction Isolation
    # -------------------------------------------------------------------------
    checkout_resp = client.post(
        "/api/v1/billing/checkout",
        json={
            "items": [{"product_id": p_a["product_id"], "quantity": "5.000"}],
            "customer_name": "Tenant A Customer",
            "payment_method": "CASH",
        },
        headers=headers_a,
    )
    assert checkout_resp.status_code == 201
    tx_a = checkout_resp.json()
    tx_a_id = tx_a["transaction_id"]

    # Tenant A can fetch transaction & receipt
    tx_fetch_a = client.get(f"/api/v1/billing/transactions/{tx_a_id}", headers=headers_a)
    assert tx_fetch_a.status_code == 200

    receipt_fetch_a = client.get(f"/api/v1/billing/transactions/{tx_a_id}/receipt", headers=headers_a)
    assert receipt_fetch_a.status_code == 200

    # Tenant B attempts to fetch Tenant A transaction -> must return 404
    tx_fetch_b = client.get(f"/api/v1/billing/transactions/{tx_a_id}", headers=headers_b)
    assert tx_fetch_b.status_code == 404

    receipt_fetch_b = client.get(f"/api/v1/billing/transactions/{tx_a_id}/receipt", headers=headers_b)
    assert receipt_fetch_b.status_code == 404

    # Tenant B listing transactions must be empty
    tx_list_b = client.get("/api/v1/billing/transactions", headers=headers_b).json()
    assert len(tx_list_b) == 0

    # -------------------------------------------------------------------------
    # 6. Cross-Tenant Payload Tampering (Reject Mismatched store_id in Body)
    # -------------------------------------------------------------------------
    # Trying to send Tenant B's store_id while authenticated in Tenant A
    tamper_prod = client.post(
        "/api/v1/inventory/products",
        json={
            "name": "Tampered Product",
            "category": "Spoof",
            "default_unit": "PIECE",
            "selling_price": "10.00",
            "store_id": store_b_id,
        },
        headers=headers_a,
    )
    assert tamper_prod.status_code == 403

    tamper_checkout = client.post(
        "/api/v1/billing/checkout",
        json={
            "items": [{"product_id": p_a["product_id"], "quantity": "1.000"}],
            "store_id": store_b_id,
        },
        headers=headers_a,
    )
    assert tamper_checkout.status_code == 403

    # -------------------------------------------------------------------------
    # 7. Standard Clerk Tenant Boundary Enforcement
    # -------------------------------------------------------------------------
    # Register a standard clerk assigned only to Tenant A
    clerk_email = f"clerk-{uuid.uuid4().hex[:6]}@tenant-a.com"
    clerk_resp = client.post(
        "/api/v1/auth/login",
        json={"email": clerk_email, "name": "Clerk A", "role": "user"},
    )
    assert clerk_resp.status_code == 200
    clerk_token = clerk_resp.json()["access_token"]
    clerk_user_id = clerk_resp.json()["user"]["user_id"]

    # Assign clerk to Tenant A
    assign_resp = client.post(
        "/api/v1/auth/assign-store",
        json={"user_id": clerk_user_id, "store_id": store_a_id},
        headers=admin_headers,
    )
    assert assign_resp.status_code == 200

    clerk_headers_a = {
        "Authorization": f"Bearer {clerk_token}",
        "X-Dev-User-Email": clerk_email,
        "X-Store-Id": store_a_id,
    }
    clerk_headers_b = {
        "Authorization": f"Bearer {clerk_token}",
        "X-Dev-User-Email": clerk_email,
        "X-Store-Id": store_b_id,
    }

    # Clerk can query Tenant A products
    clerk_list_a = client.get("/api/v1/inventory/products", headers=clerk_headers_a)
    assert clerk_list_a.status_code == 200

    # Clerk attempts to query Tenant B -> 403 Forbidden!
    clerk_list_b = client.get("/api/v1/inventory/products", headers=clerk_headers_b)
    assert clerk_list_b.status_code == 403

    # Clerk attempts to get Tenant B store info -> 403 Forbidden!
    clerk_store_b = client.get(f"/api/v1/stores/{store_b_id}", headers=clerk_headers_a)
    assert clerk_store_b.status_code == 403
