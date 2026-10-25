import uuid
from datetime import date, timedelta

from fastapi.testclient import TestClient


def test_dashboard_reporting_flows(client: TestClient, admin_headers: dict):
    # 1. Create Store
    s_resp = client.post(
        "/api/v1/stores/create",
        json={"name": f"Dashboard Store {uuid.uuid4().hex[:6]}"},
        headers=admin_headers,
    )
    store_id = s_resp.json()["store_id"]
    headers = {**admin_headers, "X-Store-Id": store_id}

    # 2. Add Products
    p1 = client.post(
        "/api/v1/inventory/products",
        json={"name": "Energy Drink", "category": "Drinks", "selling_price": "5.00", "min_stock_alert_threshold": "10.0"},
        headers=headers,
    ).json()

    p2 = client.post(
        "/api/v1/inventory/products",
        json={"name": "Protein Bar", "category": "Fitness", "selling_price": "3.00", "min_stock_alert_threshold": "20.0"},
        headers=headers,
    ).json()

    today = date.today()

    # Receive a near-expiry batch (15 days)
    client.post(
        "/api/v1/inventory/receive/single",
        json={
            "product_id": p1["product_id"],
            "batch_identifier": "EXPIRING-SOON",
            "quantity": "15.000",
            "purchase_date": today.isoformat(),
            "expiry_date": (today + timedelta(days=15)).isoformat(),
        },
        headers=headers,
    )

    # Receive a longer batch (90 days)
    client.post(
        "/api/v1/inventory/receive/single",
        json={
            "product_id": p2["product_id"],
            "batch_identifier": "SAFE-BATCH",
            "quantity": "50.000",
            "purchase_date": today.isoformat(),
            "expiry_date": (today + timedelta(days=90)).isoformat(),
        },
        headers=headers,
    )

    # Perform a transaction
    client.post(
        "/api/v1/billing/checkout",
        json={
            "store_id": store_id,
            "items": [{"product_id": p1["product_id"], "quantity": "5.000"}],
            "payment_method": "CASH",
        },
        headers=headers,
    )

    # 3. Test Dashboard Overview
    overview_resp = client.get("/api/v1/dashboard/overview", headers=headers)
    assert overview_resp.status_code == 200
    ov = overview_resp.json()
    assert ov["today_transaction_count"] == 1
    assert float(ov["today_revenue"]) == 25.0
    assert ov["batches_expiring_within_30_days"] == 1
    assert ov["total_active_products"] == 2

    # 4. Test Stock Health
    health_resp = client.get("/api/v1/dashboard/stock-health", headers=headers)
    assert health_resp.status_code == 200
    sh = health_resp.json()
    assert sh["total_critical_batches"] >= 1
    assert sh["batches"][0]["status"] == "CRITICAL_30_DAYS"

    # 5. Test Sales Velocity
    vel_resp = client.get("/api/v1/dashboard/sales-velocity?period_days=7", headers=headers)
    assert vel_resp.status_code == 200
    vel = vel_resp.json()
    assert len(vel["top_selling_items"]) >= 1
    assert vel["top_selling_items"][0]["product_name"] == "Energy Drink"
    assert float(vel["top_selling_items"][0]["total_quantity_sold"]) == 5.0

    # 6. Test Inventory Status
    inv_resp = client.get("/api/v1/dashboard/inventory-status", headers=headers)
    assert inv_resp.status_code == 200
    inv = inv_resp.json()
    assert inv["total_products"] == 2
