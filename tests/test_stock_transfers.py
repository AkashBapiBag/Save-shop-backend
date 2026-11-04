from datetime import date, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient


def test_stock_transfer_same_product_name_recalculation(client: TestClient, admin_headers: dict):
    # 1. Create Source Store and Destination Store
    s1_resp = client.post("/api/v1/stores/create", json={"name": "Source Shop Alpha"}, headers=admin_headers)
    assert s1_resp.status_code == 201
    source_store_id = s1_resp.json()["store_id"]

    s2_resp = client.post("/api/v1/stores/create", json={"name": "Dest Shop Beta"}, headers=admin_headers)
    assert s2_resp.status_code == 201
    dest_store_id = s2_resp.json()["store_id"]

    headers_s1 = {**admin_headers, "X-Store-Id": source_store_id}
    headers_s2 = {**admin_headers, "X-Store-Id": dest_store_id}

    # 2. Create "Shop XYZ" in Source Store with 30.0 units (across two batches)
    p1_resp = client.post(
        "/api/v1/inventory/products",
        json={
            "name": "Shop XYZ",
            "category": "Snacks",
            "default_unit": "KG",
            "selling_price": "25.00",
            "cost_price": "18.00",
            "min_stock_alert_threshold": "5.000",
            "barcode": "XYZ-BAR-01",
        },
        headers=headers_s1,
    )
    assert p1_resp.status_code == 201
    p1_id = p1_resp.json()["product_id"]

    today = date.today()
    client.post(
        "/api/v1/inventory/receive/single",
        json={
            "product_id": p1_id,
            "batch_identifier": "LOT-A1",
            "quantity": "10.000",
            "purchase_price": "18.00",
            "purchase_date": today.isoformat(),
            "expiry_date": (today + timedelta(days=30)).isoformat(),
        },
        headers=headers_s1,
    )
    client.post(
        "/api/v1/inventory/receive/single",
        json={
            "product_id": p1_id,
            "batch_identifier": "LOT-A2",
            "quantity": "20.000",
            "purchase_price": "18.50",
            "purchase_date": today.isoformat(),
            "expiry_date": (today + timedelta(days=60)).isoformat(),
        },
        headers=headers_s1,
    )

    # 3. Create "Shop XYZ" in Destination Store with existing 5.0 units
    p2_resp = client.post(
        "/api/v1/inventory/products",
        json={
            "name": "Shop XYZ",
            "category": "Snacks",
            "default_unit": "KG",
            "selling_price": "25.00",
            "cost_price": "18.00",
            "barcode": "XYZ-BAR-01",
        },
        headers=headers_s2,
    )
    assert p2_resp.status_code == 201
    p2_id = p2_resp.json()["product_id"]

    client.post(
        "/api/v1/inventory/receive/single",
        json={
            "product_id": p2_id,
            "batch_identifier": "DEST-LOT-1",
            "quantity": "5.000",
            "purchase_price": "18.00",
            "purchase_date": today.isoformat(),
            "expiry_date": (today + timedelta(days=90)).isoformat(),
        },
        headers=headers_s2,
    )

    # Verify initial stock
    p1_check = client.get(f"/api/v1/inventory/products/{p1_id}", headers=headers_s1).json()
    assert float(p1_check["total_current_stock"]) == 30.0

    p2_check = client.get(f"/api/v1/inventory/products/{p2_id}", headers=headers_s2).json()
    assert float(p2_check["total_current_stock"]) == 5.0

    # 4. Transfer 15.0 units from Source to Destination
    trf_resp = client.post(
        "/api/v1/inventory/transfers",
        json={
            "source_store_id": source_store_id,
            "destination_store_id": dest_store_id,
            "notes": "Replenish XYZ snacks",
            "items": [{"product_id": p1_id, "quantity": "15.000"}],
        },
        headers=admin_headers,
    )
    assert trf_resp.status_code == 201
    trf_data = trf_resp.json()
    assert trf_data["transfer_number"].startswith("TRF-")
    assert trf_data["source_store_name"] == "Source Shop Alpha"
    assert trf_data["destination_store_name"] == "Dest Shop Beta"
    assert float(trf_data["total_quantity"]) == 15.0
    assert len(trf_data["items"]) == 1
    assert trf_data["items"][0]["auto_created_product"] is False
    assert trf_data["items"][0]["destination_product_id"] == p2_id

    # 5. Verify Stocks Recalculated Accurately in both stores
    p1_after = client.get(f"/api/v1/inventory/products/{p1_id}", headers=headers_s1).json()
    assert float(p1_after["total_current_stock"]) == 15.0  # 30.0 - 15.0

    p2_after = client.get(f"/api/v1/inventory/products/{p2_id}", headers=headers_s2).json()
    assert float(p2_after["total_current_stock"]) == 20.0  # 5.0 + 15.0


def test_stock_transfer_auto_create_product_on_the_go(client: TestClient, admin_headers: dict):
    # 1. Create 2 stores
    s1 = client.post("/api/v1/stores/create", json={"name": "Origin Hub"}, headers=admin_headers).json()["store_id"]
    s2 = client.post("/api/v1/stores/create", json={"name": "Satellite Outlet"}, headers=admin_headers).json()["store_id"]
    h1 = {**admin_headers, "X-Store-Id": s1}
    h2 = {**admin_headers, "X-Store-Id": s2}

    # 2. Create unique product in Origin Hub
    prod = client.post(
        "/api/v1/inventory/products",
        json={
            "name": "Artisan Almond Butter",
            "category": "Spreads",
            "default_unit": "BOTTLE",
            "selling_price": "12.50",
            "cost_price": "8.00",
            "min_stock_alert_threshold": "4.000",
            "barcode": "ALM-BUTTER-99",
        },
        headers=h1,
    ).json()
    prod_id = prod["product_id"]

    today = date.today()
    client.post(
        "/api/v1/inventory/receive/single",
        json={
            "product_id": prod_id,
            "batch_identifier": "BATCH-BUTTER-1",
            "quantity": "25.000",
            "purchase_price": "8.00",
            "purchase_date": today.isoformat(),
            "expiry_date": (today + timedelta(days=120)).isoformat(),
        },
        headers=h1,
    )

    # Verify Satellite Outlet currently has 0 products
    s2_products = client.get("/api/v1/inventory/products", headers=h2).json()
    assert len(s2_products) == 0

    # 3. Transfer 8 bottles to Satellite Outlet (which DOES NOT have this product)
    trf_resp = client.post(
        "/api/v1/inventory/transfers",
        json={
            "source_store_id": s1,
            "destination_store_id": s2,
            "notes": "First distribution of Almond Butter",
            "items": [{"product_id": prod_id, "quantity": "8.000"}],
        },
        headers=admin_headers,
    )
    assert trf_resp.status_code == 201
    trf_data = trf_resp.json()
    assert trf_data["items"][0]["auto_created_product"] is True

    # 4. Verify Origin stock dropped to 17
    s1_check = client.get(f"/api/v1/inventory/products/{prod_id}", headers=h1).json()
    assert float(s1_check["total_current_stock"]) == 17.0

    # 5. Verify Satellite Outlet now HAS the product created on-the-go with 8.0 stock!
    s2_products = client.get("/api/v1/inventory/products", headers=h2).json()
    assert len(s2_products) == 1
    new_prod = s2_products[0]
    assert new_prod["name"] == "Artisan Almond Butter"
    assert new_prod["category"] == "Spreads"
    assert new_prod["default_unit"] == "BOTTLE"
    assert float(new_prod["selling_price"]) == 12.50
    assert float(new_prod["cost_price"]) == 8.00
    assert new_prod["barcode"] == "ALM-BUTTER-99"
    assert float(new_prod["total_current_stock"]) == 8.0


def test_stock_transfer_multi_item_batch_transfer(client: TestClient, admin_headers: dict):
    # Create 2 stores
    s1 = client.post("/api/v1/stores/create", json={"name": "Warehouse North"}, headers=admin_headers).json()["store_id"]
    s2 = client.post("/api/v1/stores/create", json={"name": "Retail South"}, headers=admin_headers).json()["store_id"]
    h1 = {**admin_headers, "X-Store-Id": s1}
    h2 = {**admin_headers, "X-Store-Id": s2}

    # Create 2 products in Warehouse
    p1 = client.post(
        "/api/v1/inventory/products",
        json={"name": "Fresh Apples", "category": "Produce", "default_unit": "KG", "selling_price": "3.00"},
        headers=h1,
    ).json()

    p2 = client.post(
        "/api/v1/inventory/products",
        json={"name": "Fresh Bananas", "category": "Produce", "default_unit": "DOZEN", "selling_price": "2.00"},
        headers=h1,
    ).json()

    today = date.today()
    exp = today + timedelta(days=20)
    client.post(
        "/api/v1/inventory/receive/single",
        json={
            "product_id": p1["product_id"],
            "batch_identifier": "APP-1",
            "quantity": "50.000",
            "purchase_date": today.isoformat(),
            "expiry_date": exp.isoformat(),
        },
        headers=h1,
    )
    client.post(
        "/api/v1/inventory/receive/single",
        json={
            "product_id": p2["product_id"],
            "batch_identifier": "BAN-1",
            "quantity": "40.000",
            "purchase_date": today.isoformat(),
            "expiry_date": exp.isoformat(),
        },
        headers=h1,
    )

    # Multi-item transfer: 15.0 KG Apples and 10.0 DOZEN Bananas
    trf_resp = client.post(
        "/api/v1/inventory/transfers",
        json={
            "source_store_id": s1,
            "destination_store_id": s2,
            "items": [
                {"product_id": p1["product_id"], "quantity": "15.000"},
                {"product_id": p2["product_id"], "quantity": "10.000"},
            ],
        },
        headers=admin_headers,
    )
    assert trf_resp.status_code == 201
    trf = trf_resp.json()
    assert trf["total_items"] == 2
    assert float(trf["total_quantity"]) == 25.0

    # Verify both products in Retail South got created with accurate stock
    s2_prods = client.get("/api/v1/inventory/products", headers=h2).json()
    assert len(s2_prods) == 2
    apple_s2 = next(p for p in s2_prods if p["name"] == "Fresh Apples")
    banana_s2 = next(p for p in s2_prods if p["name"] == "Fresh Bananas")
    assert float(apple_s2["total_current_stock"]) == 15.0
    assert float(banana_s2["total_current_stock"]) == 10.0


def test_stock_transfer_insufficient_stock_rollback(client: TestClient, admin_headers: dict):
    s1 = client.post("/api/v1/stores/create", json={"name": "Store Shortage 1"}, headers=admin_headers).json()["store_id"]
    s2 = client.post("/api/v1/stores/create", json={"name": "Store Shortage 2"}, headers=admin_headers).json()["store_id"]
    h1 = {**admin_headers, "X-Store-Id": s1}

    p = client.post(
        "/api/v1/inventory/products",
        json={"name": "Olive Oil 5L", "category": "Oils", "default_unit": "CAN", "selling_price": "45.00"},
        headers=h1,
    ).json()

    today = date.today()
    client.post(
        "/api/v1/inventory/receive/single",
        json={
            "product_id": p["product_id"],
            "batch_identifier": "CAN-01",
            "quantity": "5.000",
            "purchase_date": today.isoformat(),
            "expiry_date": (today + timedelta(days=365)).isoformat(),
        },
        headers=h1,
    )

    # Attempt to transfer 10.000 (only 5 available)
    fail_resp = client.post(
        "/api/v1/inventory/transfers",
        json={
            "source_store_id": s1,
            "destination_store_id": s2,
            "items": [{"product_id": p["product_id"], "quantity": "10.000"}],
        },
        headers=admin_headers,
    )
    assert fail_resp.status_code == 400
    assert "INSUFFICIENT_STOCK" in fail_resp.text

    # Stock must remain intact at 5
    p_check = client.get(f"/api/v1/inventory/products/{p['product_id']}", headers=h1).json()
    assert float(p_check["total_current_stock"]) == 5.0


def test_stock_transfer_same_store_rejected(client: TestClient, admin_headers: dict):
    s = client.post("/api/v1/stores/create", json={"name": "Identical Store"}, headers=admin_headers).json()["store_id"]
    h = {**admin_headers, "X-Store-Id": s}

    p = client.post(
        "/api/v1/inventory/products",
        json={"name": "Item A", "default_unit": "PIECE", "selling_price": "10.00"},
        headers=h,
    ).json()

    resp = client.post(
        "/api/v1/inventory/transfers",
        json={
            "source_store_id": s,
            "destination_store_id": s,
            "items": [{"product_id": p["product_id"], "quantity": "1.000"}],
        },
        headers=admin_headers,
    )
    assert resp.status_code == 400
    assert "cannot be the same store" in resp.text


def test_stock_transfer_history_inward_outward_filters(client: TestClient, admin_headers: dict):
    s1 = client.post("/api/v1/stores/create", json={"name": "Central Hub"}, headers=admin_headers).json()["store_id"]
    s2 = client.post("/api/v1/stores/create", json={"name": "Sub Store A"}, headers=admin_headers).json()["store_id"]
    s3 = client.post("/api/v1/stores/create", json={"name": "Sub Store B"}, headers=admin_headers).json()["store_id"]
    h1 = {**admin_headers, "X-Store-Id": s1}

    p = client.post(
        "/api/v1/inventory/products",
        json={"name": "Flour 10KG", "default_unit": "PACKET", "selling_price": "20.00"},
        headers=h1,
    ).json()

    today = date.today()
    client.post(
        "/api/v1/inventory/receive/single",
        json={
            "product_id": p["product_id"],
            "batch_identifier": "FLOUR-LOT-1",
            "quantity": "100.000",
            "purchase_date": today.isoformat(),
            "expiry_date": (today + timedelta(days=90)).isoformat(),
        },
        headers=h1,
    )

    # Transfer 1: s1 -> s2
    client.post(
        "/api/v1/inventory/transfers",
        json={
            "source_store_id": s1,
            "destination_store_id": s2,
            "notes": "Transfer to Sub A",
            "items": [{"product_id": p["product_id"], "quantity": "20.000"}],
        },
        headers=admin_headers,
    )

    # Transfer 2: s1 -> s3
    client.post(
        "/api/v1/inventory/transfers",
        json={
            "source_store_id": s1,
            "destination_store_id": s3,
            "notes": "Transfer to Sub B",
            "items": [{"product_id": p["product_id"], "quantity": "30.000"}],
        },
        headers=admin_headers,
    )

    # Query Outward from Central Hub (s1)
    outward_resp = client.get(f"/api/v1/inventory/transfers?store_id={s1}&direction=outward", headers=admin_headers)
    assert outward_resp.status_code == 200
    outward_data = outward_resp.json()
    assert len(outward_data) == 2

    # Query Inward to Sub Store A (s2)
    inward_s2 = client.get(f"/api/v1/inventory/transfers?store_id={s2}&direction=inward", headers=admin_headers).json()
    assert len(inward_s2) == 1
    assert inward_s2[0]["source_store_name"] == "Central Hub"
    assert inward_s2[0]["destination_store_name"] == "Sub Store A"
    assert float(inward_s2[0]["total_quantity"]) == 20.0

    # Query Inward to Sub Store B (s3)
    inward_s3 = client.get(f"/api/v1/inventory/transfers?store_id={s3}&direction=inward", headers=admin_headers).json()
    assert len(inward_s3) == 1
    assert inward_s3[0]["destination_store_name"] == "Sub Store B"
    assert float(inward_s3[0]["total_quantity"]) == 30.0

    # Query search by note or transfer number
    search_resp = client.get("/api/v1/inventory/transfers?search=Sub A", headers=admin_headers).json()
    assert len(search_resp) == 1
    assert search_resp[0]["notes"] == "Transfer to Sub A"

    # Query using X-Store-Id header (logical boundary enforcement without query param)
    h_s2 = {**admin_headers, "X-Store-Id": s2}
    header_resp = client.get("/api/v1/inventory/transfers?direction=all", headers=h_s2).json()
    assert len(header_resp) == 1
    assert header_resp[0]["destination_store_id"] == s2

    # Query outward from s2 using X-Store-Id header (s2 has no outward transfers)
    header_outward_resp = client.get("/api/v1/inventory/transfers?direction=outward", headers=h_s2).json()
    assert len(header_outward_resp) == 0

    # Query inward to s2 using X-Store-Id header
    header_inward_resp = client.get("/api/v1/inventory/transfers?direction=inward", headers=h_s2).json()
    assert len(header_inward_resp) == 1
    assert header_inward_resp[0]["source_store_name"] == "Central Hub"
