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

    # Verify owner cannot remove themselves
    owner_info = client.get("/api/v1/auth/me", headers=admin_headers).json()
    owner_id = owner_info["user_id"]
    self_rem_resp = client.delete(
        f"/api/v1/stores/{store_e_id}/operators/{owner_id}",
        headers=admin_headers,
    )
    assert self_rem_resp.status_code == 400
    assert "Store owners cannot remove themselves" in self_rem_resp.json()["error"]["message"]


def test_store_creator_owner_can_remove_added_admin_and_prevent_owner_removal(client: TestClient):
    # 1. Admin A logs in and creates a store
    admin_a_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "akashbapibag12@gmail.com", "name": "Akash 12 Owner", "role": "admin"},
    )
    assert admin_a_resp.status_code == 200
    admin_a_data = admin_a_resp.json()
    admin_a_id = admin_a_data["user"]["user_id"]
    admin_a_headers = {"Authorization": f"Bearer {admin_a_data['access_token']}"}

    create_store_resp = client.post(
        "/api/v1/stores/create",
        json={"name": "Akash 12 Flagship Store", "phone_number": "+919988776655"},
        headers=admin_a_headers,
    )
    assert create_store_resp.status_code in [200, 201]
    store = create_store_resp.json()
    store_id = store["store_id"]
    assert store["owner_id"] == admin_a_id

    # 2. Admin B logs in as another admin in the system (their role in DB is admin)
    admin_b_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "operator_admin_b@saveshop.com", "name": "Akash 9 Admin", "role": "admin"},
    )
    assert admin_b_resp.status_code == 200
    admin_b_data = admin_b_resp.json()
    admin_b_id = admin_b_data["user"]["user_id"]
    admin_b_headers = {"Authorization": f"Bearer {admin_b_data['access_token']}"}

    # 3. Store owner (Admin A) adds Admin B to the store by email (DB decides role: admin)
    add_b_resp = client.post(
        f"/api/v1/stores/{store_id}/operators",
        json={"email": "operator_admin_b@saveshop.com"},
        headers=admin_a_headers,
    )
    assert add_b_resp.status_code == 200
    assert add_b_resp.json()["status"] == "assigned"
    assert add_b_resp.json()["operator"]["is_owner"] is False
    assert add_b_resp.json()["operator"]["role"] == "admin"

    # 4. Check operators list
    ops_resp = client.get(f"/api/v1/stores/{store_id}/operators", headers=admin_a_headers)
    assert ops_resp.status_code == 200
    ops_data = ops_resp.json()
    assert ops_data["owner_id"] == admin_a_id
    op_map = {op["email"]: op for op in ops_data["operators"]}
    assert op_map["akashbapibag12@gmail.com"]["is_owner"] is True
    assert op_map["operator_admin_b@saveshop.com"]["is_owner"] is False
    assert op_map["operator_admin_b@saveshop.com"]["role"] == "admin"

    # 5. Added Admin B tries to remove Admin A (the store owner) -> REJECTED
    attempt_remove_owner = client.delete(
        f"/api/v1/stores/{store_id}/operators/{admin_a_id}",
        headers=admin_b_headers,
    )
    assert attempt_remove_owner.status_code in [400, 403]
    assert "Store owners cannot remove themselves" in attempt_remove_owner.json()["error"]["message"]

    # 6. Actual Store Owner (Admin A) removes Added Admin B -> SUCCEEDS
    remove_b_resp = client.delete(
        f"/api/v1/stores/{store_id}/operators/{admin_b_id}",
        headers=admin_a_headers,
    )
    assert remove_b_resp.status_code == 200
    assert "Operator access removed from store" in remove_b_resp.json()["message"]

    # 7. Verify Admin B is no longer in operators list
    ops_after = client.get(f"/api/v1/stores/{store_id}/operators", headers=admin_a_headers).json()
    op_emails_after = [op["email"] for op in ops_after["operators"]]
    assert "operator_admin_b@saveshop.com" not in op_emails_after
    assert "akashbapibag12@gmail.com" in op_emails_after


def test_single_store_owner_enforcement(client: TestClient):
    # 1. Create a store with an owner
    owner_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "sole_owner@saveshop.com", "name": "Sole Owner", "role": "admin"},
    )
    assert owner_resp.status_code == 200
    owner_headers = {"Authorization": f"Bearer {owner_resp.json()['access_token']}"}

    create_resp = client.post(
        "/api/v1/stores/create",
        json={"name": "Sole Owner Shop", "phone_number": "+919988112233"},
        headers=owner_headers,
    )
    assert create_resp.status_code == 201
    store_id = create_resp.json()["store_id"]

    # 2. Attempting to add another operator with role 'owner' must be REJECTED
    attempt_add_owner = client.post(
        f"/api/v1/stores/{store_id}/operators",
        json={"email": "second_owner@saveshop.com", "role": "owner"},
        headers=owner_headers,
    )
    assert attempt_add_owner.status_code == 400
    assert "only have 1 owner" in attempt_add_owner.json()["error"]["message"]

    # 3. Add multiple admins and cashiers
    for i, email in enumerate(["admin_two@saveshop.com", "admin_three@saveshop.com"]):
        # register users
        client.post("/api/v1/auth/login", json={"email": email, "name": f"Admin {i}", "role": "admin"})
        # add to store as admin
        client.post(
            f"/api/v1/stores/{store_id}/operators",
            json={"email": email, "role": "admin"},
            headers=owner_headers,
        )

    # 4. Fetch store operators list and assert EXACTLY 1 user has is_owner=True and is FIRST (index 0)
    ops_resp = client.get(f"/api/v1/stores/{store_id}/operators", headers=owner_headers)
    assert ops_resp.status_code == 200
    ops = ops_resp.json()["operators"]
    assert len(ops) == 3

    # Owner is always on top (1st item)
    assert ops[0]["email"] == "sole_owner@saveshop.com"
    assert ops[0]["is_owner"] is True

    owners = [op for op in ops if op["is_owner"] is True]
    assert len(owners) == 1
    assert owners[0]["email"] == "sole_owner@saveshop.com"

    non_owners = [op for op in ops if op["is_owner"] is False]
    assert len(non_owners) == 2


def test_unassigned_admin_cannot_see_or_access_store(client: TestClient):
    # 1. Admin A creates Store A
    admin_a_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "creator_admin@saveshop.com", "name": "Creator Admin", "role": "admin"},
    )
    admin_a_headers = {"Authorization": f"Bearer {admin_a_resp.json()['access_token']}"}

    create_resp = client.post(
        "/api/v1/stores/create",
        json={"name": "Creator Private Store", "phone_number": "+919988771122"},
        headers=admin_a_headers,
    )
    assert create_resp.status_code == 201
    store_a_id = create_resp.json()["store_id"]

    # 2. Admin B logs in (has role: admin, but is NOT assigned to Store A)
    admin_b_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "unassigned_admin@saveshop.com", "name": "Unassigned Admin", "role": "admin"},
    )
    admin_b_headers = {"Authorization": f"Bearer {admin_b_resp.json()['access_token']}"}

    # 3. Admin B gets their accessible stores -> Store A must NOT be visible
    b_stores = client.get("/api/v1/auth/stores", headers=admin_b_headers).json()
    b_store_ids = [s["store_id"] for s in b_stores]
    assert store_a_id not in b_store_ids

    # 4. Admin B attempts to access Store A management -> 403 Forbidden
    access_attempt = client.get(f"/api/v1/stores/{store_a_id}/operators", headers=admin_b_headers)
    assert access_attempt.status_code == 403

    # 5. Admin B attempts to switch context to Store A -> 403 Forbidden
    switch_attempt = client.post(f"/api/v1/auth/switch-store/{store_a_id}", headers=admin_b_headers)
    assert switch_attempt.status_code == 403


def test_db_role_determines_store_operator_role_admin_and_staff(client: TestClient):
    """
    Validates logical constraint:
    1. If user is admin in DB, adding them to any shop automatically makes them an admin in that shop.
    2. If user is staff (user) in DB, adding them to any shop makes them staff.
    3. A shop has strictly 1 owner, but can have multiple admins.
    """
    # 1. Store Owner creates store
    owner_login = client.post(
        "/api/v1/auth/login",
        json={"email": "shop_owner@saveshop.com", "name": "Store Owner", "role": "admin"},
    )
    owner_headers = {"Authorization": f"Bearer {owner_login.json()['access_token']}"}
    create_resp = client.post(
        "/api/v1/stores/create",
        json={"name": "Role Test Mart", "phone_number": "+919876500000"},
        headers=owner_headers,
    )
    store_id = create_resp.json()["store_id"]

    # 2. In DB, User A is created as an admin
    client.post(
        "/api/v1/auth/login",
        json={"email": "db_admin@saveshop.com", "name": "DB Admin", "role": "admin"},
    )

    # 3. In DB, User B is created as standard staff
    client.post(
        "/api/v1/auth/login",
        json={"email": "db_staff@saveshop.com", "name": "DB Staff", "role": "user"},
    )

    # 4. Add User A by email (no role specified) -> DB decides they are 'admin'
    add_a_resp = client.post(
        f"/api/v1/stores/{store_id}/operators",
        json={"email": "db_admin@saveshop.com"},
        headers=owner_headers,
    )
    assert add_a_resp.status_code == 200
    assert add_a_resp.json()["status"] == "assigned"
    assert add_a_resp.json()["operator"]["role"] == "admin"
    assert add_a_resp.json()["operator"]["is_owner"] is False

    # 5. Add User B by email (no role specified) -> DB decides they are 'user'
    add_b_resp = client.post(
        f"/api/v1/stores/{store_id}/operators",
        json={"email": "db_staff@saveshop.com"},
        headers=owner_headers,
    )
    assert add_b_resp.status_code == 200
    assert add_b_resp.json()["status"] == "assigned"
    assert add_b_resp.json()["operator"]["role"] == "user"
    assert add_b_resp.json()["operator"]["is_owner"] is False

    # 6. Verify store operators overview has 1 owner, 1 admin, 1 staff
    ops_resp = client.get(f"/api/v1/stores/{store_id}/operators", headers=owner_headers)
    assert ops_resp.status_code == 200
    operators = ops_resp.json()["operators"]
    assert len(operators) == 3

    owner_op = next(op for op in operators if op["email"] == "shop_owner@saveshop.com")
    assert owner_op["is_owner"] is True
    assert owner_op["role"] == "admin"

    admin_op = next(op for op in operators if op["email"] == "db_admin@saveshop.com")
    assert admin_op["is_owner"] is False
    assert admin_op["role"] == "admin"

    staff_op = next(op for op in operators if op["email"] == "db_staff@saveshop.com")
    assert staff_op["is_owner"] is False
    assert staff_op["role"] == "user"




