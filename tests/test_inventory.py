from datetime import date, timedelta

from fastapi.testclient import TestClient


def test_product_crud_and_stock_calculation(client: TestClient, admin_headers: dict):
    # 1. Create a Store
    s_resp = client.post(
        "/api/v1/stores/create",
        json={"name": "Inventory Test Store"},
        headers=admin_headers,
    )
    store_id = s_resp.json()["store_id"]
    headers = {**admin_headers, "X-Store-Id": store_id}

    # 2. Create Product
    p_resp = client.post(
        "/api/v1/inventory/products",
        json={
            "name": "Organic Whole Milk",
            "category": "Dairy",
            "default_unit": "LITER",
            "selling_price": "4.50",
            "cost_price": "2.80",
            "min_stock_alert_threshold": "10.000",
            "barcode": "MILK-001",
        },
        headers=headers,
    )
    assert p_resp.status_code == 201
    prod_data = p_resp.json()
    assert prod_data["name"] == "Organic Whole Milk"
    assert float(prod_data["total_current_stock"]) == 0.0
    product_id = prod_data["product_id"]

    # 3. Receive Single Batch
    today = date.today()
    exp_date = today + timedelta(days=14)
    b_resp = client.post(
        "/api/v1/inventory/receive/single",
        json={
            "product_id": product_id,
            "batch_identifier": "LOT-2026-A1",
            "quantity": "25.000",
            "purchase_price": "2.80",
            "purchase_date": today.isoformat(),
            "expiry_date": exp_date.isoformat(),
        },
        headers=headers,
    )
    assert b_resp.status_code == 201
    assert float(b_resp.json()["current_quantity"]) == 25.0

    # 4. Verify product now shows 25.0 in stock
    p_check = client.get(f"/api/v1/inventory/products/{product_id}", headers=headers)
    assert p_check.status_code == 200
    assert float(p_check.json()["total_current_stock"]) == 25.0


def test_bulk_batch_receiving(client: TestClient, admin_headers: dict):
    # Create store & product
    s_resp = client.post("/api/v1/stores/create", json={"name": "Bulk Store"}, headers=admin_headers)
    store_id = s_resp.json()["store_id"]
    headers = {**admin_headers, "X-Store-Id": store_id}

    p1 = client.post(
        "/api/v1/inventory/products",
        json={"name": "Basmati Rice", "category": "Grains", "default_unit": "KG", "selling_price": "18.00"},
        headers=headers,
    ).json()

    p2 = client.post(
        "/api/v1/inventory/products",
        json={"name": "Olive Oil", "category": "Oils", "default_unit": "LITER", "selling_price": "22.50"},
        headers=headers,
    ).json()

    today = date.today()
    bulk_payload = {
        "store_id": store_id,
        "batches": [
            {
                "product_id": p1["product_id"],
                "batch_identifier": "LOT-RICE-01",
                "quantity": "50.000",
                "purchase_price": "12.00",
                "purchase_date": today.isoformat(),
                "expiry_date": (today + timedelta(days=365)).isoformat(),
            },
            {
                "product_id": p2["product_id"],
                "batch_identifier": "LOT-OIL-01",
                "quantity": "30.000",
                "purchase_price": "15.00",
                "purchase_date": today.isoformat(),
                "expiry_date": (today + timedelta(days=180)).isoformat(),
            },
        ],
    }

    bulk_resp = client.post("/api/v1/inventory/receive/bulk", json=bulk_payload, headers=headers)
    assert bulk_resp.status_code == 201
    assert len(bulk_resp.json()) == 2


def test_batch_date_validation_rejects_past_expiry(client: TestClient, admin_headers: dict):
    s_resp = client.post("/api/v1/stores/create", json={"name": "Date Val Store"}, headers=admin_headers)
    store_id = s_resp.json()["store_id"]
    headers = {**admin_headers, "X-Store-Id": store_id}

    p = client.post(
        "/api/v1/inventory/products",
        json={"name": "Fresh Bread", "default_unit": "PIECE", "selling_price": "2.50"},
        headers=headers,
    ).json()

    today = date.today()
    invalid_exp = today - timedelta(days=5)  # Expiry earlier than purchase date

    resp = client.post(
        "/api/v1/inventory/receive/single",
        json={
            "product_id": p["product_id"],
            "batch_identifier": "EXPIRED-LOT",
            "quantity": "10.000",
            "purchase_date": today.isoformat(),
            "expiry_date": invalid_exp.isoformat(),
        },
        headers=headers,
    )
    assert resp.status_code == 422  # Pydantic validation rejected


def test_product_create_and_update_with_discount(client: TestClient, admin_headers: dict):
    s_resp = client.post("/api/v1/stores/create", json={"name": "Discount Store"}, headers=admin_headers)
    store_id = s_resp.json()["store_id"]
    headers = {**admin_headers, "X-Store-Id": store_id}

    # 1. Create product with discount (15%) and cashback (5%)
    p_resp = client.post(
        "/api/v1/inventory/products",
        json={
            "name": "Discounted Cashews",
            "category": "Snacks",
            "default_unit": "PACKET",
            "selling_price": "200.00",
            "cost_price": "140.00",
            "min_stock_alert_threshold": "15.000",
            "discount_value": "15.00",
            "discount_type": "percentage",
            "cashback_value": "5.00",
            "cashback_type": "percentage",
        },
        headers=headers,
    )
    assert p_resp.status_code == 201
    prod = p_resp.json()
    assert prod["name"] == "Discounted Cashews"
    assert float(prod["discount_value"]) == 15.0
    assert prod["discount_type"] == "percentage"
    assert float(prod["cashback_value"]) == 5.0
    assert prod["cashback_type"] == "percentage"
    product_id = prod["product_id"]

    # 2. Update product: name, category, low stock count (min_stock_alert_threshold), discount_value, cashback_value
    update_resp = client.put(
        f"/api/v1/inventory/products/{product_id}",
        json={
            "name": "Premium Roasted Cashews",
            "category": "Dry Fruits",
            "min_stock_alert_threshold": "20.000",
            "discount_value": "25.00",
            "discount_type": "amount",
            "cashback_value": "10.00",
            "cashback_type": "amount",
        },
        headers=headers,
    )
    assert update_resp.status_code == 200
    updated = update_resp.json()
    assert updated["name"] == "Premium Roasted Cashews"
    assert updated["category"] == "Dry Fruits"
    assert float(updated["min_stock_alert_threshold"]) == 20.0
    assert float(updated["discount_value"]) == 25.0
    assert updated["discount_type"] == "amount"
    assert float(updated["cashback_value"]) == 10.0
    assert updated["cashback_type"] == "amount"
    # Verify selling price unchanged
    assert float(updated["selling_price"]) == 200.0
