from fastapi.testclient import TestClient
from app.models.product import Product


def test_place_order_success_deducts_inventory(
    client: TestClient,
    sample_product: Product,
    normal_user_token_headers: dict,
    db,
):
    initial_stock = sample_product.stock  # 15
    payload = {
        "shipping_address": "123 Tech Boulevard, Silicon Valley, CA",
        "items": [{"product_id": sample_product.id, "quantity": 3}],
    }
    resp = client.post("/api/v1/orders/", json=payload, headers=normal_user_token_headers)
    assert resp.status_code == 201
    order = resp.json()
    assert order["status"] == "PENDING"
    assert order["total_amount"] == round(3 * 89.99, 2)
    assert len(order["items"]) == 1

    # Verify inventory was atomically decremented in database
    db.refresh(sample_product)
    assert sample_product.stock == initial_stock - 3  # 12


def test_place_order_insufficient_stock_fails(
    client: TestClient,
    sample_product: Product,
    normal_user_token_headers: dict,
):
    # Requesting 20 when only 15 are available
    payload = {
        "shipping_address": "456 Developer Way, Austin, TX",
        "items": [{"product_id": sample_product.id, "quantity": 20}],
    }
    resp = client.post("/api/v1/orders/", json=payload, headers=normal_user_token_headers)
    assert resp.status_code == 400
    assert "Insufficient stock" in resp.json()["detail"]


def test_cancel_order_restores_inventory(
    client: TestClient,
    sample_product: Product,
    normal_user_token_headers: dict,
    db,
):
    # Place order for 4 items
    payload = {
        "shipping_address": "789 Cloud Ave, Seattle, WA",
        "items": [{"product_id": sample_product.id, "quantity": 4}],
    }
    order_resp = client.post("/api/v1/orders/", json=payload, headers=normal_user_token_headers)
    order_id = order_resp.json()["id"]

    db.refresh(sample_product)
    assert sample_product.stock == 11

    # Cancel order
    cancel_resp = client.post(f"/api/v1/orders/{order_id}/cancel", headers=normal_user_token_headers)
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "CANCELLED"

    # Inventory must be restored
    db.refresh(sample_product)
    assert sample_product.stock == 15


def test_illegal_status_transition_fails(
    client: TestClient,
    sample_product: Product,
    normal_user_token_headers: dict,
    admin_token_headers: dict,
):
    # Place order
    payload = {
        "shipping_address": "101 Docker Lane, Miami, FL",
        "items": [{"product_id": sample_product.id, "quantity": 1}],
    }
    order_id = client.post("/api/v1/orders/", json=payload, headers=normal_user_token_headers).json()["id"]

    # Cancel order
    client.post(f"/api/v1/orders/{order_id}/cancel", headers=normal_user_token_headers)

    # Attempt illegal transition: CANCELLED -> SHIPPED
    patch_resp = client.patch(
        f"/api/v1/orders/{order_id}/status",
        json={"status": "SHIPPED"},
        headers=admin_token_headers,
    )
    assert patch_resp.status_code == 400
    assert "Cannot transition order" in patch_resp.json()["detail"]


def test_payment_webhook_marks_order_paid(
    client: TestClient,
    sample_product: Product,
    normal_user_token_headers: dict,
):
    # Place order
    payload = {
        "shipping_address": "202 Kubernetes Blvd, Denver, CO",
        "items": [{"product_id": sample_product.id, "quantity": 2}],
    }
    order_id = client.post("/api/v1/orders/", json=payload, headers=normal_user_token_headers).json()["id"]

    # Send webhook
    webhook_payload = {
        "event": "payment.succeeded",
        "order_id": order_id,
        "payment_reference": "ch_3NabcXYZ123",
        "status": "succeeded",
    }
    hook_resp = client.post("/api/v1/webhooks/payment", json=webhook_payload)
    assert hook_resp.status_code == 200
    assert hook_resp.json()["order_status"] == "PAID"

    # Verify order status in GET
    get_resp = client.get(f"/api/v1/orders/{order_id}", headers=normal_user_token_headers)
    assert get_resp.json()["status"] == "PAID"
