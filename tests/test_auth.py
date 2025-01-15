from fastapi.testclient import TestClient


def test_register_user_success(client: TestClient):
    payload = {
        "email": "new.user@domain.com",
        "password": "StrongPassword99!",
        "full_name": "New Developer",
    }
    resp = client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == payload["email"]
    assert data["full_name"] == payload["full_name"]
    assert "hashed_password" not in data
    assert data["id"] is not None


def test_register_duplicate_email_fails(client: TestClient, normal_user):
    payload = {
        "email": normal_user.email,
        "password": "AnyPassword123!",
        "full_name": "Duplicate User",
    }
    resp = client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 400
    assert "already exists" in resp.json()["detail"]


def test_login_success(client: TestClient, normal_user):
    login_data = {
        "username": normal_user.email,
        "password": "SecretPassword123!",
    }
    resp = client.post("/api/v1/auth/login", data=login_data)
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == normal_user.email


def test_login_wrong_password_fails(client: TestClient, normal_user):
    login_data = {
        "username": normal_user.email,
        "password": "WrongPassword!",
    }
    resp = client.post("/api/v1/auth/login", data=login_data)
    assert resp.status_code == 401


def test_read_me_profile(client: TestClient, normal_user, normal_user_token_headers):
    resp = client.get("/api/v1/auth/me", headers=normal_user_token_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == normal_user.id
    assert data["email"] == normal_user.email
