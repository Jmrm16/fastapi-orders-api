import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.models.product import Product


def test_inventory_depletion_boundary_and_rejection(
    client: TestClient,
    db: Session,
    normal_user_token_headers: dict,
    sample_product: Product,
):
    """
    Inventory Boundary & Zero-Overselling Guard:
    Verifies that when a product's stock is depleted to zero, any subsequent
    order request is strictly rejected with HTTP 400 (Insufficient Stock).
    Stock must never fall into negative numbers.
    """
    initial_stock = 4
    sample_product.stock = initial_stock
    db.commit()
    db.refresh(sample_product)

    order_payload = {
        "shipping_address": "Av. El Dorado # 69-76, Bogotá, Colombia",
        "items": [{"product_id": sample_product.id, "quantity": 1}],
    }

    # 1. Place orders one by one to consume all available stock
    for i in range(initial_stock):
        resp = client.post(
            "/api/v1/orders/",
            json=order_payload,
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 201
        db.refresh(sample_product)
        assert sample_product.stock == initial_stock - (i + 1)

    # 2. At this point, stock must be exactly 0
    assert sample_product.stock == 0

    # 3. Next attempt MUST fail with 400 Bad Request
    fail_resp = client.post(
        "/api/v1/orders/",
        json=order_payload,
        headers=normal_user_token_headers,
    )
    assert fail_resp.status_code == 400
    err_body = fail_resp.json()
    assert "Insufficient" in err_body["detail"] or "stock" in err_body["detail"].lower()

    # 4. Stock remains strictly 0
    db.refresh(sample_product)
    assert sample_product.stock == 0


def test_bulk_order_exceeding_total_inventory_fails_atomically(
    client: TestClient,
    db: Session,
    normal_user_token_headers: dict,
    sample_product: Product,
):
    """
    Atomicity Test:
    Attempting to order quantity > available stock fails immediately without
    modifying any inventory.
    """
    initial_stock = sample_product.stock
    resp = client.post(
        "/api/v1/orders/",
        json={
            "shipping_address": "Carrera 7 # 32-16, Medellín, Colombia",
            "items": [{"product_id": sample_product.id, "quantity": initial_stock + 10}],
        },
        headers=normal_user_token_headers,
    )
    assert resp.status_code == 400
    db.refresh(sample_product)
    assert sample_product.stock == initial_stock
