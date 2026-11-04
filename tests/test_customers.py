import uuid
from datetime import date, timedelta

from fastapi.testclient import TestClient


def setup_customer_test_store(client: TestClient, admin_headers: dict) -> tuple[str, dict]:
    s_resp = client.post(
        "/api/v1/stores/create",
        json={"name": f"Customer Store {uuid.uuid4().hex[:6]}", "phone_number": "999-888-7777"},
        headers=admin_headers,
    )
    assert s_resp.status_code in [200, 201]
    store_id = s_resp.json()["store_id"]
    headers = {**admin_headers, "X-Store-Id": store_id}
    return store_id, headers


def test_customer_creation_with_and_without_phone(client: TestClient, admin_headers: dict):
    _, headers = setup_customer_test_store(client, admin_headers)

    # 1. Customer with phone
    res1 = client.post(
        "/api/v1/customers",
        json={
            "name": "Rajesh Sharma",
            "phone": "9876543210",
            "email": "rajesh@example.com",
            "address": "123 MG Road, Kolkata",
        },
        headers=headers,
    )
    assert res1.status_code == 201
    c1 = res1.json()
    assert c1["name"] == "Rajesh Sharma"
    assert c1["phone"] == "9876543210"
    assert c1["total_orders"] == 0
    assert float(c1["total_spent"]) == 0.0

    # 2. Customer without phone (phone is optional as per requirement)
    res2 = client.post(
        "/api/v1/customers",
        json={
            "name": "Priya Verma",
            "phone": None,
            "notes": "Prefers paper bag",
        },
        headers=headers,
    )
    assert res2.status_code == 201
    c2 = res2.json()
    assert c2["name"] == "Priya Verma"
    assert c2["phone"] is None
    assert c2["notes"] == "Prefers paper bag"


def test_existing_customer_proceeds_without_error(client: TestClient, admin_headers: dict):
    _, headers = setup_customer_test_store(client, admin_headers)

    res1 = client.post(
        "/api/v1/customers",
        json={"name": "Customer One", "phone": "9123456789"},
        headers=headers,
    )
    assert res1.status_code in [200, 201]
    c1 = res1.json()

    # When user is already saved in the database, cool to proceed with existing customer
    res2 = client.post(
        "/api/v1/customers",
        json={"name": "Customer One", "phone": "9123456789"},
        headers=headers,
    )
    assert res2.status_code in [200, 201]
    c2 = res2.json()
    assert c2["customer_id"] == c1["customer_id"]
    assert c2["phone"] == "9123456789"


def test_customer_search_and_sort(client: TestClient, admin_headers: dict):
    _, headers = setup_customer_test_store(client, admin_headers)

    client.post("/api/v1/customers", json={"name": "Ananya Roy", "phone": "9800000001"}, headers=headers)
    client.post("/api/v1/customers", json={"name": "Vikram Sen", "phone": "9800000002"}, headers=headers)
    client.post("/api/v1/customers", json={"name": "Anita Bose", "phone": "9700000003"}, headers=headers)

    # Search by name substring
    search_name = client.get("/api/v1/customers?search=Ani", headers=headers)
    assert search_name.status_code == 200
    results = search_name.json()
    assert len(results) == 1
    assert results[0]["name"] == "Anita Bose"

    # Search by phone substring
    search_phone = client.get("/api/v1/customers?search=97000", headers=headers)
    assert search_phone.status_code == 200
    p_results = search_phone.json()
    assert len(p_results) == 1
    assert p_results[0]["name"] == "Anita Bose"

    # Sort by name
    sorted_name = client.get("/api/v1/customers?sort_by=name", headers=headers)
    assert sorted_name.status_code == 200
    names = [c["name"] for c in sorted_name.json()]
    assert names == ["Ananya Roy", "Anita Bose", "Vikram Sen"]

    # Sort by recent (default)
    sorted_recent = client.get("/api/v1/customers?sort_by=recent", headers=headers)
    assert sorted_recent.status_code == 200
    assert len(sorted_recent.json()) == 3

    # Sort by orders
    sorted_orders = client.get("/api/v1/customers?sort_by=orders", headers=headers)
    assert sorted_orders.status_code == 200
    assert len(sorted_orders.json()) == 3

    # Sort by spent
    sorted_spent = client.get("/api/v1/customers?sort_by=spent", headers=headers)
    assert sorted_spent.status_code == 200
    assert len(sorted_spent.json()) == 3


def test_billing_checkout_with_customer_id_and_history(client: TestClient, admin_headers: dict):
    store_id, headers = setup_customer_test_store(client, admin_headers)

    # 1. Create a customer
    cust_res = client.post(
        "/api/v1/customers",
        json={"name": "Amit Banerjee", "phone": "9830098300"},
        headers=headers,
    )
    assert cust_res.status_code == 201
    cust = cust_res.json()
    cust_id = cust["customer_id"]

    # 2. Create a product & receive stock
    p_res = client.post(
        "/api/v1/inventory/products",
        json={
            "name": "Darjeeling Tea",
            "category": "Beverages",
            "default_unit": "PACKET",
            "selling_price": "250.00",
            "min_stock_alert_threshold": "2",
        },
        headers=headers,
    )
    assert p_res.status_code in [200, 201]
    prod = p_res.json()

    client.post(
        "/api/v1/inventory/receive/single",
        json={
            "product_id": prod["product_id"],
            "batch_identifier": "BATCH-TEA-01",
            "quantity": "20",
            "purchase_price": "180.00",
            "purchase_date": str(date.today()),
            "expiry_date": str(date.today() + timedelta(days=180)),
        },
        headers=headers,
    )

    # 3. Perform POS checkout selecting this customer
    checkout_res = client.post(
        "/api/v1/billing/checkout",
        json={
            "customer_id": cust_id,
            "items": [{"product_id": prod["product_id"], "quantity": "2"}],
            "payment_method": "UPI",
            "received_amount": "500.00",
        },
        headers=headers,
    )
    assert checkout_res.status_code == 201
    tx = checkout_res.json()
    assert tx["customer_id"] == cust_id
    assert tx["customer_name"] == "Amit Banerjee"
    assert tx["customer_phone"] == "9830098300"
    assert float(tx["final_total"]) == 500.0

    # 4. Check receipt data
    receipt_res = client.get(f"/api/v1/billing/transactions/{tx['transaction_id']}/receipt", headers=headers)
    assert receipt_res.status_code == 200
    receipt = receipt_res.json()
    assert receipt["customer_id"] == cust_id
    assert receipt["customer_name"] == "Amit Banerjee"

    # 5. Check customer profile aggregates updated
    cust_profile = client.get(f"/api/v1/customers/{cust_id}", headers=headers)
    assert cust_profile.status_code == 200
    profile_data = cust_profile.json()
    assert profile_data["total_orders"] == 1
    assert float(profile_data["total_spent"]) == 500.0
    assert profile_data["last_order_date"] is not None

    # 6. Check customer purchase history endpoint
    history_res = client.get(f"/api/v1/customers/{cust_id}/history", headers=headers)
    assert history_res.status_code == 200
    history = history_res.json()
    assert history["total_orders"] == 1
    assert float(history["total_spent"]) == 500.0
    assert len(history["transactions"]) == 1
    assert history["transactions"][0]["invoice_number"] == tx["invoice_number"]
    assert history["transactions"][0]["items_count"] == 1


def test_customer_tenant_isolation(client: TestClient, admin_headers: dict):
    _, headers1 = setup_customer_test_store(client, admin_headers)
    _, headers2 = setup_customer_test_store(client, admin_headers)

    # Create customer in Store 1
    c1 = client.post(
        "/api/v1/customers",
        json={"name": "Store1 Customer", "phone": "9000000001"},
        headers=headers1,
    ).json()

    # Store 2 listing customers should be empty
    list_s2 = client.get("/api/v1/customers", headers=headers2).json()
    assert len(list_s2) == 0

    # Store 2 cannot retrieve Store 1's customer
    get_cross = client.get(f"/api/v1/customers/{c1['customer_id']}", headers=headers2)
    assert get_cross.status_code == 404


def test_customer_common_between_two_stores(client: TestClient, admin_headers: dict):
    """
    Verifies that a customer can be common across 2 stores:
    - Customer is created in Store 1
    - Store 2 registers customer with same phone: links seamlessly without duplicate error
    - Both stores list the customer in their phonebooks with is_multi_store=True
    - Store 2 cannot register the same phone a third time (rejected within Store 2)
    """
    store_id1, headers1 = setup_customer_test_store(client, admin_headers)
    store_id2, headers2 = setup_customer_test_store(client, admin_headers)

    # 1. Create in Store 1
    res1 = client.post(
        "/api/v1/customers",
        json={"name": "Subhash Chandra", "phone": "9831098310", "email": "subhash@netaji.in"},
        headers=headers1,
    )
    assert res1.status_code == 201
    c1 = res1.json()
    assert c1["name"] == "Subhash Chandra"
    assert c1["phone"] == "9831098310"
    assert c1["is_multi_store"] is False

    # 2. Store 2 adds customer with same phone number -> Should link existing customer without error!
    res2 = client.post(
        "/api/v1/customers",
        json={"name": "Subhash Chandra Bose", "phone": "9831098310", "address": "Elgin Road, Kolkata"},
        headers=headers2,
    )
    assert res2.status_code == 201
    c2 = res2.json()
    # Same customer_id!
    assert c2["customer_id"] == c1["customer_id"]
    assert c2["phone"] == "9831098310"
    assert c2["is_multi_store"] is True
    assert set(c2["store_ids"]) == {store_id1, store_id2}

    # 3. Both stores now list this customer in their phonebook
    list1 = client.get("/api/v1/customers", headers=headers1).json()
    assert len(list1) == 1
    assert list1[0]["customer_id"] == c1["customer_id"]
    assert list1[0]["is_multi_store"] is True

    list2 = client.get("/api/v1/customers", headers=headers2).json()
    assert len(list2) == 1
    assert list2[0]["customer_id"] == c1["customer_id"]
    assert list2[0]["is_multi_store"] is True

    # 4. Adding same phone again returns existing customer without error
    res_dup = client.post(
        "/api/v1/customers",
        json={"name": "Subhash Chandra Bose", "phone": "9831098310"},
        headers=headers2,
    )
    assert res_dup.status_code in [200, 201]
    assert res_dup.json()["customer_id"] == c1["customer_id"]


def test_customer_common_billing_across_two_stores(client: TestClient, admin_headers: dict):
    """
    Verifies POS billing for a common customer across 2 stores:
    - Customer created in Store 1
    - Store 2 bills customer via checkout -> succeeds and auto-links without breaking
    - History tracks store-level and network-level metrics
    """
    store_id1, headers1 = setup_customer_test_store(client, admin_headers)
    store_id2, headers2 = setup_customer_test_store(client, admin_headers)

    # 1. Customer created in Store 1
    c1 = client.post(
        "/api/v1/customers",
        json={"name": "Kavita Krishnamurthy", "phone": "9820011223"},
        headers=headers1,
    ).json()
    cust_id = c1["customer_id"]

    # 2. Create products in Store 1 and Store 2
    p1 = client.post(
        "/api/v1/inventory/products",
        json={"name": "Store 1 Rice", "category": "Grains", "default_unit": "KG", "selling_price": "60.00"},
        headers=headers1,
    ).json()
    client.post(
        "/api/v1/inventory/receive/single",
        json={
            "product_id": p1["product_id"],
            "batch_identifier": "B1",
            "quantity": "50",
            "purchase_price": "40.00",
            "purchase_date": str(date.today()),
            "expiry_date": str(date.today() + timedelta(days=90)),
        },
        headers=headers1,
    )

    p2 = client.post(
        "/api/v1/inventory/products",
        json={"name": "Store 2 Wheat", "category": "Grains", "default_unit": "KG", "selling_price": "45.00"},
        headers=headers2,
    ).json()
    client.post(
        "/api/v1/inventory/receive/single",
        json={
            "product_id": p2["product_id"],
            "batch_identifier": "B2",
            "quantity": "50",
            "purchase_price": "30.00",
            "purchase_date": str(date.today()),
            "expiry_date": str(date.today() + timedelta(days=90)),
        },
        headers=headers2,
    )

    # 3. Bill in Store 1
    tx1 = client.post(
        "/api/v1/billing/checkout",
        json={
            "customer_id": cust_id,
            "items": [{"product_id": p1["product_id"], "quantity": "2"}],
            "payment_method": "CASH",
            "received_amount": "120.00",
        },
        headers=headers1,
    ).json()
    assert float(tx1["final_total"]) == 120.0

    # 4. Bill in Store 2 with same customer_id -> Must NOT break!
    tx2 = client.post(
        "/api/v1/billing/checkout",
        json={
            "customer_id": cust_id,
            "items": [{"product_id": p2["product_id"], "quantity": "4"}],
            "payment_method": "UPI",
            "received_amount": "180.00",
        },
        headers=headers2,
    )
    assert tx2.status_code == 201
    tx2_data = tx2.json()
    assert float(tx2_data["final_total"]) == 180.0
    assert tx2_data["customer_name"] == "Kavita Krishnamurthy"

    # 5. Check Store 1 history
    h1 = client.get(f"/api/v1/customers/{cust_id}/history", headers=headers1).json()
    assert h1["total_orders"] == 1
    assert float(h1["total_spent"]) == 120.0
    assert h1["all_stores_orders"] == 2
    assert float(h1["all_stores_spent"]) == 300.0

    # 6. Check Store 2 history
    h2 = client.get(f"/api/v1/customers/{cust_id}/history", headers=headers2).json()
    assert h2["total_orders"] == 1
    assert float(h2["total_spent"]) == 180.0
    assert h2["all_stores_orders"] == 2
    assert float(h2["all_stores_spent"]) == 300.0

