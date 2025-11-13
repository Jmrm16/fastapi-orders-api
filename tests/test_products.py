from fastapi.testclient import TestClient


def test_list_products_empty(client: TestClient):
    resp = client.get("/api/v1/products/")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_products_with_items(client: TestClient, sample_product):
    resp = client.get("/api/v1/products/")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["sku"] == sample_product.sku
    assert items[0]["name"] == sample_product.name


def test_search_product_by_query(client: TestClient, sample_product):
    # Match query
    resp = client.get("/api/v1/products/?search=Keyboard")
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    # Unmatched query
    resp = client.get("/api/v1/products/?search=NonExistentMonitor")
    assert resp.status_code == 200
    assert len(resp.json()) == 0


def test_create_product_admin_only(client: TestClient, admin_token_headers, normal_user_token_headers):
    payload = {
        "sku": "MOUSE-PRO-WIRELESS",
        "name": "Precision Gaming Mouse",
        "description": "Ergonomic 26K DPI sensor",
        "price": 59.99,
        "stock": 30,
        "is_active": True,
    }
    # Regular customer should be forbidden (403)
    resp_user = client.post("/api/v1/products/", json=payload, headers=normal_user_token_headers)
    assert resp_user.status_code == 403

    # Admin should succeed (201)
    resp_admin = client.post("/api/v1/products/", json=payload, headers=admin_token_headers)
    assert resp_admin.status_code == 201
    data = resp_admin.json()
    assert data["sku"] == payload["sku"]
    assert data["stock"] == 30


def test_update_product_stock_admin(client: TestClient, sample_product, admin_token_headers):
    patch_data = {"stock": 50, "price": 79.99}
    resp = client.patch(
        f"/api/v1/products/{sample_product.id}",
        json=patch_data,
        headers=admin_token_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["stock"] == 50
    assert data["price"] == 79.99
