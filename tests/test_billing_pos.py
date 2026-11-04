import uuid
from datetime import date, timedelta

from fastapi.testclient import TestClient


def setup_pos_test_environment(client: TestClient, admin_headers: dict):
    # 1. Create Store
    s_resp = client.post(
        "/api/v1/stores/create",
        json={"name": f"POS Store {uuid.uuid4().hex[:6]}", "phone_number": "123-456-7890"},
        headers=admin_headers,
    )
    store_id = s_resp.json()["store_id"]
    headers = {**admin_headers, "X-Store-Id": store_id}

    # 2. Create Product 1 (Snacks category)
    p1 = client.post(
        "/api/v1/inventory/products",
        json={
            "name": "Potato Chips",
            "category": "Snacks",
            "default_unit": "PACKET",
            "selling_price": "10.00",
            "min_stock_alert_threshold": "3.000",
        },
        headers=headers,
    ).json()

    # 3. Create Product 2 (Beverages category)
    p2 = client.post(
        "/api/v1/inventory/products",
        json={
            "name": "Fresh Orange Juice",
            "category": "Beverages",
            "default_unit": "BOTTLE",
            "selling_price": "30.00",
            "min_stock_alert_threshold": "5.000",
        },
        headers=headers,
    ).json()

    today = date.today()

    # Receive 2 batches for Product 1 (FEFO test)
    # Batch A: Expires in 10 days, qty 5
    client.post(
        "/api/v1/inventory/receive/single",
        json={
            "product_id": p1["product_id"],
            "batch_identifier": "BATCH-CHIPS-EARLY",
            "quantity": "5.000",
            "purchase_date": today.isoformat(),
            "expiry_date": (today + timedelta(days=10)).isoformat(),
        },
        headers=headers,
    )

    # Batch B: Expires in 30 days, qty 10
    client.post(
        "/api/v1/inventory/receive/single",
        json={
            "product_id": p1["product_id"],
            "batch_identifier": "BATCH-CHIPS-LATE",
            "quantity": "10.000",
            "purchase_date": today.isoformat(),
            "expiry_date": (today + timedelta(days=30)).isoformat(),
        },
        headers=headers,
    )

    # Receive 1 batch for Product 2
    client.post(
        "/api/v1/inventory/receive/single",
        json={
            "product_id": p2["product_id"],
            "batch_identifier": "BATCH-JUICE-01",
            "quantity": "20.000",
            "purchase_date": today.isoformat(),
            "expiry_date": (today + timedelta(days=60)).isoformat(),
        },
        headers=headers,
    )

    return store_id, headers, p1, p2


def test_pos_fefo_stock_depletion(client: TestClient, admin_headers: dict):
    store_id, headers, p1, _ = setup_pos_test_environment(client, admin_headers)

    # Product 1 has:
    # - BATCH-CHIPS-EARLY: 5 units (expires in 10 days)
    # - BATCH-CHIPS-LATE: 10 units (expires in 30 days)
    # Total = 15 units.
    # Purchase 7 units. Under FEFO, all 5 from EARLY should be used, plus 2 from LATE.
    checkout_payload = {
        "store_id": store_id,
        "items": [
            {
                "product_id": p1["product_id"],
                "quantity": "7.000",
            }
        ],
        "payment_method": "CASH",
    }

    resp = client.post("/api/v1/billing/checkout", json=checkout_payload, headers=headers)
    assert resp.status_code == 201
    data = resp.json()

    allocations = data["items"][0]["allocations"]
    assert len(allocations) == 2
    # Allocation 1: BATCH-CHIPS-EARLY should have deducted 5
    assert allocations[0]["batch_identifier"] == "BATCH-CHIPS-EARLY"
    assert float(allocations[0]["quantity_deducted"]) == 5.0

    # Allocation 2: BATCH-CHIPS-LATE should have deducted 2
    assert allocations[1]["batch_identifier"] == "BATCH-CHIPS-LATE"
    assert float(allocations[1]["quantity_deducted"]) == 2.0

    # Check updated batches in inventory (including depleted)
    batches = client.get(
        f"/api/v1/inventory/batches?product_id={p1['product_id']}&only_active=false",
        headers=headers,
    ).json()
    early_batch = next(b for b in batches if b["batch_identifier"] == "BATCH-CHIPS-EARLY")
    late_batch = next(b for b in batches if b["batch_identifier"] == "BATCH-CHIPS-LATE")

    assert float(early_batch["current_quantity"]) == 0.0
    assert float(late_batch["current_quantity"]) == 8.0


def test_pos_3_tier_discounts_calculation(client: TestClient, admin_headers: dict):
    """
    Tests Section 3.1:
    Price Calculation: Quantity * UnitPrice.
    Discount Application:
    1. Item Level: % discount on item
    2. Category Level: % discount on category
    3. Total Level: % discount on subtotal
    """
    store_id, headers, p1, p2 = setup_pos_test_environment(client, admin_headers)

    # Item 1: Potato Chips (Snacks category), $10 each, qty 2
    # Base: $20.00
    # Item discount: 10% -> -$2.00 -> $18.00
    # Category discount for Snacks: 10% -> -$1.80 -> $16.20

    # Item 2: Juice (Beverages category), $30 each, qty 1
    # Base: $30.00
    # Item discount: 0% -> $30.00
    # Category discount for Beverages: 20% -> -$6.00 -> $24.00

    # Intermediate Subtotal = $16.20 + $24.00 = $40.20
    # Total Level Discount: 10% on intermediate subtotal = -$4.02
    # Final Total = $40.20 - $4.02 = $36.18

    checkout_payload = {
        "store_id": store_id,
        "items": [
            {
                "product_id": p1["product_id"],
                "quantity": "2.000",
                "item_discount_pct": "10.00",
            },
            {
                "product_id": p2["product_id"],
                "quantity": "1.000",
                "item_discount_pct": "0.00",
            },
        ],
        "category_discounts": [
            {"category": "Snacks", "discount_pct": "10.00"},
            {"category": "Beverages", "discount_pct": "20.00"},
        ],
        "total_discount_pct": "10.00",
        "payment_method": "UPI",
    }

    resp = client.post("/api/v1/billing/checkout", json=checkout_payload, headers=headers)
    assert resp.status_code == 201
    tx = resp.json()

    assert float(tx["subtotal"]) == 50.00  # 20 + 30
    assert float(tx["item_discount_amount"]) == 2.00  # 10% of 20
    assert float(tx["category_discount_amount"]) == 7.80  # 1.80 + 6.00
    assert float(tx["total_discount_amount"]) == 4.02  # 10% of 40.20
    assert float(tx["final_total"]) == 36.18


def test_pos_insufficient_stock_rollback(client: TestClient, admin_headers: dict):
    store_id, headers, p1, _ = setup_pos_test_environment(client, admin_headers)

    # When allow_negative_stock=False, attempting to purchase 100 with only 15 units should fail.
    resp = client.post(
        "/api/v1/billing/checkout",
        json={
            "store_id": store_id,
            "items": [{"product_id": p1["product_id"], "quantity": "100.000"}],
            "allow_negative_stock": False,
        },
        headers=headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INSUFFICIENT_STOCK"

    # Confirm stock was not deducted (still 15)
    prod = client.get(f"/api/v1/inventory/products/{p1['product_id']}", headers=headers).json()
    assert float(prod["total_current_stock"]) == 15.0


def test_pos_negative_stock_allowed_and_restock_adjustment(client: TestClient, admin_headers: dict):
    """
    Tests that:
    1. POS billing allows checkout even when stock is insufficient (default allow_negative_stock=True).
    2. Over-purchased items drive product stock into negative values (-5 units).
    3. At the time of restock, the incoming batch quantity adjusts/settles the negative stock overdraft.
    """
    store_id, headers, p1, _ = setup_pos_test_environment(client, admin_headers)
    # p1 initially has 15 units across 2 batches (5 in EARLY, 10 in LATE)
    today = date.today()

    # Purchase 20 units (5 more than the 15 available)
    resp = client.post(
        "/api/v1/billing/checkout",
        json={
            "store_id": store_id,
            "items": [{"product_id": p1["product_id"], "quantity": "20.000"}],
            "payment_method": "CASH",
        },
        headers=headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["invoice_number"].startswith("INV-")

    # Product stock should now be negative 5 (-5.000)
    prod = client.get(f"/api/v1/inventory/products/{p1['product_id']}", headers=headers).json()
    assert float(prod["total_current_stock"]) == -5.0

    # Restock with a new batch of 12 units
    # -5 deficit should be settled to 0, and the new batch should have 7 available units (-5 + 12 = 7)
    restock_resp = client.post(
        "/api/v1/inventory/receive/single",
        json={
            "product_id": p1["product_id"],
            "batch_identifier": "BATCH-RESTOCK-01",
            "quantity": "12.000",
            "purchase_price": "10.00",
            "purchase_date": today.isoformat(),
            "expiry_date": (today + timedelta(days=90)).isoformat(),
        },
        headers=headers,
    )
    assert restock_resp.status_code == 201
    new_batch_data = restock_resp.json()
    assert float(new_batch_data["initial_quantity"]) == 12.0
    assert float(new_batch_data["current_quantity"]) == 7.0

    # Total stock should now be exactly 7.000
    prod_after = client.get(f"/api/v1/inventory/products/{p1['product_id']}", headers=headers).json()
    assert float(prod_after["total_current_stock"]) == 7.0


def test_pos_structured_receipt_endpoint(client: TestClient, admin_headers: dict):
    store_id, headers, p1, _ = setup_pos_test_environment(client, admin_headers)

    # Complete a transaction
    tx_resp = client.post(
        "/api/v1/billing/checkout",
        json={
            "store_id": store_id,
            "items": [{"product_id": p1["product_id"], "quantity": "1.000"}],
            "customer_name": "Alice Wonderland",
            "customer_phone": "+1555123456",
        },
        headers=headers,
    )
    tx_id = tx_resp.json()["transaction_id"]

    # Fetch structured receipt
    receipt_resp = client.get(f"/api/v1/billing/transactions/{tx_id}/receipt", headers=headers)
    assert receipt_resp.status_code == 200
    receipt = receipt_resp.json()

    assert receipt["customer_name"] == "Alice Wonderland"
    assert "store" in receipt
    assert receipt["store"]["state"] is not None
    assert "invoice_number" in receipt
    assert len(receipt["items"]) == 1
    assert "final_total" in receipt


def test_pos_cashback_and_subtotal_discount_amount(client: TestClient, admin_headers: dict):
    store_id, headers, p1, p2 = setup_pos_test_environment(client, admin_headers)

    # Product 1: Potato Chips (selling_price = 10.00), qty 2 => line_base = 20.00
    # Cashback: 5% => 1.00
    # Product 2: Orange Juice (selling_price = 30.00), qty 1 => line_base = 30.00
    # Cashback: fixed 5.00
    # Subtotal = 50.00
    # Total Cashback = 1.00 + 5.00 = 6.00
    # Subtotal discount in amount: 10.00 (discount_type="amount")
    # Final total = 40.00

    checkout_payload = {
        "store_id": store_id,
        "items": [
            {
                "product_id": p1["product_id"],
                "quantity": "2.000",
                "cashback_pct": "5.00",
            },
            {
                "product_id": p2["product_id"],
                "quantity": "1.000",
                "cashback_amount": "5.00",
            },
        ],
        "discount_type": "amount",
        "total_discount_amount": "10.00",
        "payment_method": "CASH",
        "customer_name": "Rohan Sharma",
        "customer_phone": "9876543210",
    }

    resp = client.post("/api/v1/billing/checkout", json=checkout_payload, headers=headers)
    assert resp.status_code == 201
    data = resp.json()

    assert float(data["subtotal"]) == 50.00
    assert float(data["total_discount_amount"]) == 10.00
    assert float(data["final_total"]) == 40.00
    assert float(data["total_cashback_amount"]) == 6.00
    assert data["amount_in_words"] == "Forty Rupees only"
    assert float(data["you_saved_amount"]) == 10.00

    # Line item 1 should have received proportional discount: 10.00 * (20 / 50) = 4.00
    item1 = data["items"][0]
    assert float(item1["cashback_amount"]) == 1.00
    assert float(item1["discount_amount"]) == 4.00
    assert float(item1["line_total"]) == 16.00

    # Line item 2: 10.00 * (30 / 50) = 6.00
    item2 = data["items"][1]
    assert float(item2["cashback_amount"]) == 5.00
    assert float(item2["discount_amount"]) == 6.00
    assert float(item2["line_total"]) == 24.00

    # Test receipt response format
    tx_id = data["transaction_id"]
    receipt_resp = client.get(f"/api/v1/billing/transactions/{tx_id}/receipt", headers=headers)
    assert receipt_resp.status_code == 200
    receipt = receipt_resp.json()
    assert float(receipt["total_cashback_amount"]) == 6.00
    assert receipt["amount_in_words"] == "Forty Rupees only"
    assert receipt["store"]["state"] == "19-West Bengal"
    assert float(receipt["received_amount"]) == 40.00
    assert float(receipt["balance_amount"]) == 0.00
    assert float(receipt["you_saved_amount"]) == 10.00

    # Test CREDIT transaction: Received is 0.00, Balance is full amount
    credit_payload = {
        "store_id": store_id,
        "items": [{"product_id": p1["product_id"], "quantity": "1.000"}],
        "payment_method": "CREDIT",
        "customer_name": "Credit Customer",
        "customer_phone": "9876543210",
    }
    credit_resp = client.post("/api/v1/billing/checkout", json=credit_payload, headers=headers)
    assert credit_resp.status_code == 201
    c_data = credit_resp.json()
    assert float(c_data["final_total"]) == 10.00
    assert float(c_data["received_amount"]) == 0.00
    assert float(c_data["balance_amount"]) == 10.00
    assert c_data["payment_status"] == "PENDING"


def test_pos_validate_cart_stock_endpoint(client: TestClient, admin_headers: dict):
    store_id, headers, p1, p2 = setup_pos_test_environment(client, admin_headers)

    # p1 has 15 units, p2 has 20 units
    # Valid check
    valid_resp = client.post(
        "/api/v1/billing/validate-stock",
        json={
            "items": [
                {"product_id": p1["product_id"], "quantity": "5.000"},
                {"product_id": p2["product_id"], "quantity": "10.000"},
            ]
        },
        headers=headers,
    )
    assert valid_resp.status_code == 200
    assert valid_resp.json()["is_valid"] is True
    assert len(valid_resp.json()["errors"]) == 0

    # Invalid check (exceeding stock)
    invalid_resp = client.post(
        "/api/v1/billing/validate-stock",
        json={
            "items": [
                {"product_id": p1["product_id"], "quantity": "50.000"},
            ]
        },
        headers=headers,
    )
    assert invalid_resp.status_code == 200
    inv_data = invalid_resp.json()
    assert inv_data["is_valid"] is False
    assert len(inv_data["errors"]) == 1
    assert "available in stock" in inv_data["errors"][0]["message"]


def test_pos_sales_history_search_and_filters(client: TestClient, admin_headers: dict):
    store_id, headers, p1, _ = setup_pos_test_environment(client, admin_headers)

    # Create transaction with specific customer name
    client.post(
        "/api/v1/billing/checkout",
        json={
            "store_id": store_id,
            "items": [{"product_id": p1["product_id"], "quantity": "1.000"}],
            "customer_name": "Suresh Raina",
            "customer_phone": "9998887776",
        },
        headers=headers,
    )

    # Search by customer name
    search_resp = client.get(
        "/api/v1/billing/transactions?search=Suresh",
        headers=headers,
    )
    assert search_resp.status_code == 200
    results = search_resp.json()
    assert len(results) >= 1
    assert any(tx["customer_name"] == "Suresh Raina" for tx in results)

    # Search with no match
    no_match_resp = client.get(
        "/api/v1/billing/transactions?search=NonExistentCustomerXYZ",
        headers=headers,
    )
    assert no_match_resp.status_code == 200
    assert len(no_match_resp.json()) == 0

    # Filter with date_filter=today
    today_resp = client.get(
        "/api/v1/billing/transactions?date_filter=today",
        headers=headers,
    )
    assert today_resp.status_code == 200
    assert len(today_resp.json()) >= 1


def test_pos_incremental_unique_invoice_numbering(client: TestClient, admin_headers: dict):
    """
    Verifies that invoice numbers in DB are strictly incremental (1, 2, 3...)
    and unique per store.
    """
    store_id, headers, p1, _ = setup_pos_test_environment(client, admin_headers)

    # 1. Create 3 consecutive transactions for store A
    tx1 = client.post(
        "/api/v1/billing/checkout",
        json={"items": [{"product_id": p1["product_id"], "quantity": "1.000"}], "payment_method": "CASH"},
        headers=headers,
    ).json()

    tx2 = client.post(
        "/api/v1/billing/checkout",
        json={"items": [{"product_id": p1["product_id"], "quantity": "1.000"}], "payment_method": "CASH"},
        headers=headers,
    ).json()

    tx3 = client.post(
        "/api/v1/billing/checkout",
        json={"items": [{"product_id": p1["product_id"], "quantity": "1.000"}], "payment_method": "CASH"},
        headers=headers,
    ).json()

    assert tx1["invoice_seq"] == 1
    assert tx1["invoice_number"] == "INV-00001"

    assert tx2["invoice_seq"] == 2
    assert tx2["invoice_number"] == "INV-00002"

    assert tx3["invoice_seq"] == 3
    assert tx3["invoice_number"] == "INV-00003"

    # Verify structured receipt reflects sequence
    receipt_resp = client.get(f"/api/v1/billing/transactions/{tx2['transaction_id']}/receipt", headers=headers)
    assert receipt_resp.status_code == 200
    receipt = receipt_resp.json()
    assert receipt["invoice_seq"] == 2
    assert receipt["invoice_number"] == "INV-00002"


def test_pos_discount_calculated_from_stock_product(client: TestClient, admin_headers: dict):
    """
    Verifies that during POS billing, discount is automatically calculated
    from the product in stock (no manual discount input required from cashier).
    """
    s_resp = client.post("/api/v1/stores/create", json={"name": "Auto Disc Store"}, headers=admin_headers)
    store_id = s_resp.json()["store_id"]
    headers = {**admin_headers, "X-Store-Id": store_id}

    # 1. Product with 10% discount in stock
    p = client.post(
        "/api/v1/inventory/products",
        json={
            "name": "Tea Pack",
            "category": "Beverages",
            "default_unit": "PACKET",
            "selling_price": "100.00",
            "discount_value": "10.00",
            "discount_type": "percentage",
        },
        headers=headers,
    ).json()

    # Receive stock
    today = date.today()
    client.post(
        "/api/v1/inventory/receive/single",
        json={
            "product_id": p["product_id"],
            "batch_identifier": "LOT-TEA-1",
            "quantity": "20.000",
            "purchase_price": "60.00",
            "purchase_date": today.isoformat(),
            "expiry_date": (today + timedelta(days=90)).isoformat(),
        },
        headers=headers,
    )

    # 2. Checkout: cashier specifies NO manual subtotal discount
    checkout_payload = {
        "store_id": store_id,
        "items": [
            {
                "product_id": p["product_id"],
                "quantity": "2.000",
            }
        ],
        "payment_method": "CASH",
    }

    resp = client.post("/api/v1/billing/checkout", json=checkout_payload, headers=headers)
    assert resp.status_code == 201
    tx = resp.json()

    # Subtotal: 2 * 100 = 200.00
    assert float(tx["subtotal"]) == 200.00
    # Automatically calculated discount from stock product: 10% of 200 = 20.00
    assert float(tx["item_discount_amount"]) == 20.00
    # Final total: 200 - 20 = 180.00
    assert float(tx["final_total"]) == 180.00
    assert float(tx["you_saved_amount"]) == 20.00
    assert float(tx["items"][0]["discount_amount"]) == 20.00
    assert float(tx["items"][0]["line_total"]) == 180.00


def test_pos_cashback_and_discount_calculated_from_stock_product(client: TestClient, admin_headers: dict):
    """
    Verifies that during POS billing, both discount AND cashback are automatically
    calculated from the product in stock without requiring any manual calculation or input.
    """
    s_resp = client.post("/api/v1/stores/create", json={"name": "Auto Disc & CB Store"}, headers=admin_headers)
    store_id = s_resp.json()["store_id"]
    headers = {**admin_headers, "X-Store-Id": store_id}

    # 1. Product with 10% discount and 5% cashback in stock
    p = client.post(
        "/api/v1/inventory/products",
        json={
            "name": "Organic Honey",
            "category": "Groceries",
            "default_unit": "BOTTLE",
            "selling_price": "200.00",
            "discount_value": "10.00",
            "discount_type": "percentage",
            "cashback_value": "5.00",
            "cashback_type": "percentage",
        },
        headers=headers,
    ).json()

    # Receive stock
    today = date.today()
    client.post(
        "/api/v1/inventory/receive/single",
        json={
            "product_id": p["product_id"],
            "batch_identifier": "LOT-HONEY-1",
            "quantity": "50.000",
            "purchase_price": "120.00",
            "purchase_date": today.isoformat(),
            "expiry_date": (today + timedelta(days=180)).isoformat(),
        },
        headers=headers,
    )

    # 2. Checkout: cashier specifies NO manual discount and NO manual cashback
    checkout_payload = {
        "store_id": store_id,
        "items": [
            {
                "product_id": p["product_id"],
                "quantity": "2.000",
            }
        ],
        "payment_method": "UPI",
    }

    resp = client.post("/api/v1/billing/checkout", json=checkout_payload, headers=headers)
    assert resp.status_code == 201
    tx = resp.json()

    # Subtotal: 2 * 200 = 400.00
    assert float(tx["subtotal"]) == 400.00
    # Automatically calculated discount from stock product: 10% of 400 = 40.00
    assert float(tx["item_discount_amount"]) == 40.00
    # Final total: 400 - 40 = 360.00
    assert float(tx["final_total"]) == 360.00
    # Automatically calculated cashback from stock product: 5% of 400 = 20.00
    assert float(tx["total_cashback_amount"]) == 20.00
    assert float(tx["items"][0]["cashback_amount"]) == 20.00
    assert float(tx["items"][0]["cashback_pct"]) == 5.00


def test_pos_walk_in_customer_cannot_buy_on_credit_or_have_dues(client: TestClient, admin_headers: dict):
    """
    Verifies that walk-in customers are not given credit options or permitted
    to have pending dues. They must pay in full at checkout.
    """
    store_id, headers, p1, _ = setup_pos_test_environment(client, admin_headers)

    # 1. Attempt checkout with CREDIT for walk-in customer -> 400
    credit_payload = {
        "store_id": store_id,
        "customer_name": "Walk-in Customer",
        "items": [{"product_id": p1["product_id"], "quantity": "1"}],
        "payment_method": "CREDIT",
    }
    resp1 = client.post("/api/v1/billing/checkout", json=credit_payload, headers=headers)
    assert resp1.status_code == 400
    assert "Walk-in customers cannot make purchases on credit" in resp1.json()["error"]["message"]

    # 2. Attempt checkout with partial payment for walk-in customer -> 400
    partial_payload = {
        "store_id": store_id,
        "customer_name": "Walk-in Customer",
        "items": [{"product_id": p1["product_id"], "quantity": "1"}],
        "payment_method": "CASH",
        "received_amount": "5.00",  # Total is 10.00
    }
    resp2 = client.post("/api/v1/billing/checkout", json=partial_payload, headers=headers)
    assert resp2.status_code == 400
    assert "Walk-in customers cannot make purchases on credit or leave a pending balance due" in resp2.json()["error"]["message"]

    # 3. Full payment for walk-in customer -> 201 Success
    full_payload = {
        "store_id": store_id,
        "customer_name": "Walk-in Customer",
        "items": [{"product_id": p1["product_id"], "quantity": "1"}],
        "payment_method": "CASH",
        "received_amount": "10.00",
    }
    resp3 = client.post("/api/v1/billing/checkout", json=full_payload, headers=headers)
    assert resp3.status_code == 201
    assert resp3.json()["payment_status"] == "PAID"
    assert float(resp3.json()["balance_amount"]) == 0.0

