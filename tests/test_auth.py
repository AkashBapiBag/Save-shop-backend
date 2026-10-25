from fastapi.testclient import TestClient


def test_google_sso_login_success(client: TestClient):
    # Test Google SSO token exchange via /api/v1/auth/login
    resp = client.post(
        "/api/v1/auth/login",
        json={"google_token": "mock-google-token:operator@saveshop.com:Store Operator"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["user"]["email"] == "operator@saveshop.com"
    assert data["user"]["name"] == "Store Operator"


def test_google_sso_endpoint(client: TestClient):
    # Test dedicated /api/v1/auth/google endpoint
    resp = client.post(
        "/api/v1/auth/google",
        json={"id_token": "mock-google-token:admin@saveshop.com:Chief Admin"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["user"]["role"] == "admin"
    assert data["user"]["email"] == "admin@saveshop.com"


def test_direct_login_rejected_when_dev_disabled(client: TestClient, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ENABLE_DEV_DIRECT_LOGIN", False)
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")

    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "unauthorized@saveshop.com", "name": "Direct User"},
    )
    assert resp.status_code == 401
    assert "Direct login without SSO is disabled" in resp.json()["error"]["message"]


def test_auth_login_admin(client: TestClient, admin_headers: dict):
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@saveshop.com", "name": "Admin User", "role": "admin"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["user"]["role"] == "admin"
    assert data["user"]["email"] == "admin@saveshop.com"


def test_auth_me(client: TestClient, admin_headers: dict):
    resp = client.get("/api/v1/auth/me", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["email"] == "admin@saveshop.com"


def test_user_store_switching_restriction(client: TestClient, admin_headers: dict, standard_user_headers: dict):
    # 1. Admin creates Store 1 and Store 2
    s1_resp = client.post(
        "/api/v1/stores/create",
        json={"name": "Downtown Branch", "phone_number": "+1234567890"},
        headers=admin_headers,
    )
    assert s1_resp.status_code == 201

    s2_resp = client.post(
        "/api/v1/stores/create",
        json={"name": "Uptown Branch", "phone_number": "+1234567891"},
        headers=admin_headers,
    )
    assert s2_resp.status_code == 201
    s2_id = s2_resp.json()["store_id"]

    # 2. Standard user attempts to switch to Store 2 without assignment -> 403 Forbidden
    switch_resp = client.post(
        f"/api/v1/auth/switch-store/{s2_id}",
        headers=standard_user_headers,
    )
    assert switch_resp.status_code == 403
    assert switch_resp.json()["error"]["code"] == "FORBIDDEN"

    # 3. Admin assigns standard user to Store 2
    user_me = client.get("/api/v1/auth/me", headers=standard_user_headers).json()
    assign_resp = client.post(
        "/api/v1/auth/assign-store",
        json={"user_id": user_me["user_id"], "store_id": s2_id},
        headers=admin_headers,
    )
    assert assign_resp.status_code == 200

    # 4. Standard user now switches to Store 2 -> Success
    switch_ok = client.post(
        f"/api/v1/auth/switch-store/{s2_id}",
        headers=standard_user_headers,
    )
    assert switch_ok.status_code == 200
    assert switch_ok.json()["current_store_id"] == s2_id
