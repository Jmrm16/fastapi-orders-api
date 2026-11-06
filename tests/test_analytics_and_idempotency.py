import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.models.product import Product


def test_telemetry_headers_present_on_all_responses(client: TestClient):
    """Verifies that the observability middleware injects request ID and latency headers."""
    response = client.get("/health")
    assert response.status_code == 200
    assert "x-request-id" in response.headers
    assert "x-process-time" in response.headers
    assert response.headers["x-process-time"].endswith("s")


def test_idempotent_order_placement_prevents_duplicate_charge(
    client: TestClient,
    db: Session,
    normal_user_token_headers: dict,
    sample_product: Product,
):
    """
    Stripe-grade duplicate prevention:
    Repeated POST requests bearing the same Idempotency-Key header must return
    the exact existing order without re-decrementing inventory.
    """
    initial_stock = sample_product.stock
    order_payload = {
        "shipping_address": "Calle 10 # 5-20, Maicao, Colombia",
        "items": [{"product_id": sample_product.id, "quantity": 2}],
    }
    idempotency_key = "idemp-key-unique-9988"

    # First attempt: succeeds and reserves stock
    resp1 = client.post(
        "/api/v1/orders/",
        json=order_payload,
        headers={**normal_user_token_headers, "Idempotency-Key": idempotency_key},
    )
    assert resp1.status_code == 201
    order1 = resp1.json()
    assert order1["idempotency_key"] == idempotency_key

    db.refresh(sample_product)
    assert sample_product.stock == initial_stock - 2

    # Second attempt with IDENTICAL idempotency key (e.g., client timeout or double click)
    resp2 = client.post(
        "/api/v1/orders/",
        json=order_payload,
        headers={**normal_user_token_headers, "Idempotency-Key": idempotency_key},
    )
    assert resp2.status_code == 201
    order2 = resp2.json()

    # Must return the SAME order entity
    assert order2["id"] == order1["id"]
    assert order2["total_amount"] == order1["total_amount"]

    # Stock must NOT be deducted again
    db.refresh(sample_product)
    assert sample_product.stock == initial_stock - 2


def test_analytics_summary_admin_endpoint(
    client: TestClient,
    admin_token_headers: dict,
    normal_user_token_headers: dict,
    sample_product: Product,
):
    """
    Validates that the admin analytics endpoint computes financial aggregates,
    order counts, and top-selling product breakdowns accurately.
    """
    # 1. Place an order first
    client.post(
        "/api/v1/orders/",
        json={
            "shipping_address": "Zona Industrial, Carrera 40 # 12-05",
            "items": [{"product_id": sample_product.id, "quantity": 3}],
        },
        headers=normal_user_token_headers,
    )

    # 2. Query analytics as admin
    response = client.get("/api/v1/orders/analytics/summary", headers=admin_token_headers)
    assert response.status_code == 200
    data = response.json()

    assert data["total_orders"] >= 1
    assert data["total_revenue"] > 0
    assert data["average_order_value"] > 0
    assert "PENDING" in data["status_breakdown"]
    assert len(data["top_selling_products"]) >= 1

    top_item = data["top_selling_products"][0]
    assert top_item["product_id"] == sample_product.id
    assert top_item["units_sold"] >= 3


def test_analytics_summary_forbidden_for_regular_users(
    client: TestClient,
    normal_user_token_headers: dict,
):
    """Non-admin users must be rejected with 403 Forbidden when requesting business analytics."""
    response = client.get("/api/v1/orders/analytics/summary", headers=normal_user_token_headers)
    assert response.status_code == 403
