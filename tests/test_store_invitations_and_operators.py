import uuid
from fastapi.testclient import TestClient


def test_operator_auto_assignment_on_login_single_store(client: TestClient, admin_headers: dict):
    # 1. Admin creates Store A
    s_resp = client.post(
        "/api/v1/stores/create",
        json={"name": "Alpha Supermarket", "phone_number": "+919876543210"},
        headers=admin_headers,
    )
    assert s_resp.status_code == 201
    store_a_id = s_resp.json()["store_id"]

    # 2. Store Owner adds new user by email before the user ever registers or logs in
    new_user_email = "newoperator@saveshop.com"
    add_resp = client.post(
        f"/api/v1/stores/{store_a_id}/operators",
        json={"email": new_user_email, "role": "user"},
        headers=admin_headers,
    )
    assert add_resp.status_code == 200
    res_data = add_resp.json()
    assert res_data["status"] == "invited"
    assert res_data["invitation"]["email"] == new_user_email

    # 3. Check store operators overview shows pending invitation
    ops_resp = client.get(f"/api/v1/stores/{store_a_id}/operators", headers=admin_headers)
    assert ops_resp.status_code == 200
    ops_data = ops_resp.json()
    assert any(inv["email"] == new_user_email for inv in ops_data["invitations"])

    # 4. User logs in for the very first time using Google SSO token
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"google_token": f"mock-google-token:{new_user_email}:Alice Cashier"},
    )
    assert login_resp.status_code == 200
    login_data = login_resp.json()
    token = login_data["access_token"]
    user_info = login_data["user"]

    # Verify user was automatically assigned to Store A!
    assert user_info["email"] == new_user_email
    assert user_info["current_store_id"] == store_a_id
    assert store_a_id in [str(sid) for sid in user_info["accessible_store_ids"]]

    # 5. User fetches accessible stores -> returns Store A
    user_headers = {"Authorization": f"Bearer {token}"}
    stores_resp = client.get("/api/v1/auth/stores", headers=user_headers)
    assert stores_resp.status_code == 200
    user_stores = stores_resp.json()
    assert len(user_stores) == 1
    assert user_stores[0]["store_id"] == store_a_id

    # 6. Store operator overview now shows user as active member, and invitation no longer pending
    ops_resp2 = client.get(f"/api/v1/stores/{store_a_id}/operators", headers=admin_headers)
    assert ops_resp2.status_code == 200
    ops_data2 = ops_resp2.json()
    assert any(m["email"] == new_user_email for m in ops_data2["members"])
    assert not any(inv["email"] == new_user_email for inv in ops_data2["invitations"])


def test_operator_multiple_stores_access_and_switching(client: TestClient, admin_headers: dict):
    # 1. Admin creates Store 1 and Store 2
    s1_resp = client.post(
        "/api/v1/stores/create",
        json={"name": "Metro Branch 1", "phone_number": "+919876543211"},
        headers=admin_headers,
    )
    assert s1_resp.status_code == 201
    s1_id = s1_resp.json()["store_id"]

    s2_resp = client.post(
        "/api/v1/stores/create",
        json={"name": "Metro Branch 2", "phone_number": "+919876543212"},
        headers=admin_headers,
    )
    assert s2_resp.status_code == 201
    s2_id = s2_resp.json()["store_id"]

    multi_user_email = "roamingcashier@saveshop.com"

    # 2. Store Owner adds roamingcashier to BOTH stores before they log in
    client.post(
        f"/api/v1/stores/{s1_id}/operators",
        json={"email": multi_user_email, "role": "user"},
        headers=admin_headers,
    )
    client.post(
        f"/api/v1/stores/{s2_id}/operators",
        json={"email": multi_user_email, "role": "user"},
        headers=admin_headers,
    )

    # 3. User logs in for the first time
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": multi_user_email, "name": "Roaming Cashier", "role": "user"},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]
    user_headers = {"Authorization": f"Bearer {token}"}

    # 4. Operator fetches accessible stores -> has access to BOTH stores
    stores_resp = client.get("/api/v1/auth/stores", headers=user_headers)
    assert stores_resp.status_code == 200
    stores_data = stores_resp.json()
    store_ids = [s["store_id"] for s in stores_data]
    assert s1_id in store_ids
    assert s2_id in store_ids

    # 5. Switch active store to Store 2
    switch_resp = client.post(f"/api/v1/auth/switch-store/{s2_id}", headers=user_headers)
    assert switch_resp.status_code == 200
    assert switch_resp.json()["current_store_id"] == s2_id

    # 6. Switch active store back to Store 1
    switch_back = client.post(f"/api/v1/auth/switch-store/{s1_id}", headers=user_headers)
    assert switch_back.status_code == 200
    assert switch_back.json()["current_store_id"] == s1_id


def test_add_existing_user_by_email_instantly_assigns(client: TestClient, admin_headers: dict):
    # 1. Standard user already exists in the system
    user_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "existinguser@saveshop.com", "name": "Existing User", "role": "user"},
    )
    assert user_resp.status_code == 200
    user_id = user_resp.json()["user"]["user_id"]
    token = user_resp.json()["access_token"]
    user_headers = {"Authorization": f"Bearer {token}"}

    # Verify existing user currently has no stores
    stores_pre = client.get("/api/v1/auth/stores", headers=user_headers).json()
    assert len(stores_pre) == 0

    # 2. Store Owner creates Store C
    s_resp = client.post(
        "/api/v1/stores/create",
        json={"name": "Charlie Mart", "phone_number": "+919876543213"},
        headers=admin_headers,
    )
    store_c_id = s_resp.json()["store_id"]

    # 3. Store Owner adds existing user by email
    add_resp = client.post(
        f"/api/v1/stores/{store_c_id}/operators",
        json={"email": "existinguser@saveshop.com", "role": "user"},
        headers=admin_headers,
    )
    assert add_resp.status_code == 200
    assert add_resp.json()["status"] == "assigned"
    assert add_resp.json()["operator"]["user_id"] == user_id

    # 4. User refreshes /auth/stores -> Store C is now accessible
    stores_post = client.get("/api/v1/auth/stores", headers=user_headers).json()
    assert len(stores_post) == 1
    assert stores_post[0]["store_id"] == store_c_id


def test_assign_store_backward_compatibility_with_email(client: TestClient, admin_headers: dict):
    s_resp = client.post(
        "/api/v1/stores/create",
        json={"name": "Delta Branch", "phone_number": "+919876543214"},
        headers=admin_headers,
    )
    store_d_id = s_resp.json()["store_id"]

    # Using /api/v1/auth/assign-store with email
    assign_resp = client.post(
        "/api/v1/auth/assign-store",
        json={"email": "futureoperator@saveshop.com", "store_id": store_d_id},
        headers=admin_headers,
    )
    assert assign_resp.status_code == 200
    assert assign_resp.json()["data"]["status"] == "invited"


def test_remove_operator_and_revoke_invitation(client: TestClient, admin_headers: dict):
    s_resp = client.post(
        "/api/v1/stores/create",
        json={"name": "Echo Store", "phone_number": "+919876543215"},
        headers=admin_headers,
    )
    store_e_id = s_resp.json()["store_id"]

    # 1. Invite a non-existent email
    add_inv = client.post(
        f"/api/v1/stores/{store_e_id}/operators",
        json={"email": "to_revoke@saveshop.com"},
        headers=admin_headers,
    )
    inv_id = add_inv.json()["invitation"]["invitation_id"]

    # Revoke invitation
    rev_resp = client.delete(
        f"/api/v1/stores/{store_e_id}/invitations/{inv_id}",
        headers=admin_headers,
    )
    assert rev_resp.status_code == 200

    # 2. Add an existing user and then remove operator
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "temp_clerk@saveshop.com", "name": "Temp Clerk", "role": "user"},
    )
    user_id = login_resp.json()["user"]["user_id"]

    client.post(
        f"/api/v1/stores/{store_e_id}/operators",
        json={"email": "temp_clerk@saveshop.com"},
        headers=admin_headers,
    )

    rem_resp = client.delete(
        f"/api/v1/stores/{store_e_id}/operators/{user_id}",
        headers=admin_headers,
    )
    assert rem_resp.status_code == 200

    # Verify temp_clerk has no access
    token = login_resp.json()["access_token"]
    stores_resp = client.get("/api/v1/auth/stores", headers={"Authorization": f"Bearer {token}"})
    assert len(stores_resp.json()) == 0
