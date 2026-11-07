import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.models.product import Product
from app.models.coupon import Coupon, DiscountType


def test_admin_create_and_list_coupons(
    client: TestClient,
    admin_token_headers: dict,
    normal_user_token_headers: dict,
):
    # 1. Non-admin is forbidden
    forbidden_resp = client.post(
        "/api/v1/coupons/",
        json={
            "code": "HACK20",
            "discount_type": "PERCENTAGE",
            "discount_value": 20.0,
            "min_order_amount": 50.0,
        },
        headers=normal_user_token_headers,
    )
    assert forbidden_resp.status_code == 403

    # 2. Admin creates valid percentage coupon
    resp = client.post(
        "/api/v1/coupons/",
        json={
            "code": "welcome20",  # lowercase should be normalized to WELCOME20
            "discount_type": "PERCENTAGE",
            "discount_value": 20.0,
            "min_order_amount": 50.0,
            "max_uses": 100,
        },
        headers=admin_token_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["code"] == "WELCOME20"
    assert data["discount_value"] == 20.0
    assert data["times_used"] == 0

    # 3. Duplicate code fails
    dup_resp = client.post(
        "/api/v1/coupons/",
        json={
            "code": "WELCOME20",
            "discount_type": "PERCENTAGE",
            "discount_value": 10.0,
        },
        headers=admin_token_headers,
    )
    assert dup_resp.status_code == 400


def test_coupon_preview_validation_endpoint(
    client: TestClient,
    db: Session,
    normal_user_token_headers: dict,
):
    coupon = Coupon(
        code="SAVE15",
        discount_type=DiscountType.FIXED,
        discount_value=15.0,
        min_order_amount=60.0,
        is_active=True,
    )
    db.add(coupon)
    db.commit()

    # Subtotal $40 does not meet min $60 requirement
    resp_under = client.get(
        "/api/v1/coupons/validate/SAVE15?subtotal=40.0",
        headers=normal_user_token_headers,
    )
    assert resp_under.status_code == 200
    res_data = resp_under.json()
    assert res_data["is_valid"] is False
    assert res_data["estimated_discount"] == 0.0

    # Subtotal $100 meets requirement
    resp_valid = client.get(
        "/api/v1/coupons/validate/SAVE15?subtotal=100.0",
        headers=normal_user_token_headers,
    )
    assert resp_valid.status_code == 200
    val_data = resp_valid.json()
    assert val_data["is_valid"] is True
    assert val_data["estimated_discount"] == 15.0


def test_checkout_applies_percentage_discount_correctly(
    client: TestClient,
    db: Session,
    normal_user_token_headers: dict,
    sample_product: Product,
):
    sample_product.price = 100.0
    sample_product.stock = 10
    coupon = Coupon(
        code="PROMO10",
        discount_type=DiscountType.PERCENTAGE,
        discount_value=10.0,
        min_order_amount=50.0,
        is_active=True,
    )
    db.add(coupon)
    db.commit()

    resp = client.post(
        "/api/v1/orders/",
        json={
            "shipping_address": "Calle 72 # 10-34, Bogotá, Colombia",
            "items": [{"product_id": sample_product.id, "quantity": 1}],
            "coupon_code": "PROMO10",
        },
        headers=normal_user_token_headers,
    )
    assert resp.status_code == 201
    order_data = resp.json()
    assert order_data["subtotal"] == 100.0
    assert order_data["discount_amount"] == 10.0
    assert order_data["total_amount"] == 90.0

    db.refresh(coupon)
    assert coupon.times_used == 1


def test_checkout_fails_on_expired_coupon(
    client: TestClient,
    db: Session,
    normal_user_token_headers: dict,
    sample_product: Product,
):
    yesterday = datetime.utcnow() - timedelta(days=1)
    coupon = Coupon(
        code="EXPIRED50",
        discount_type=DiscountType.PERCENTAGE,
        discount_value=50.0,
        valid_until=yesterday,
        is_active=True,
    )
    db.add(coupon)
    db.commit()

    resp = client.post(
        "/api/v1/orders/",
        json={
            "shipping_address": "Av. Las Americas # 45-12, Cali",
            "items": [{"product_id": sample_product.id, "quantity": 1}],
            "coupon_code": "EXPIRED50",
        },
        headers=normal_user_token_headers,
    )
    assert resp.status_code == 400
    assert "expired" in resp.json()["detail"].lower()


def test_checkout_fails_when_coupon_max_uses_reached(
    client: TestClient,
    db: Session,
    normal_user_token_headers: dict,
    sample_product: Product,
):
    coupon = Coupon(
        code="ONETIMEONLY",
        discount_type=DiscountType.FIXED,
        discount_value=5.0,
        max_uses=1,
        times_used=1,
        is_active=True,
    )
    db.add(coupon)
    db.commit()

    resp = client.post(
        "/api/v1/orders/",
        json={
            "shipping_address": "Carrera 43A # 1-50, Medellín",
            "items": [{"product_id": sample_product.id, "quantity": 1}],
            "coupon_code": "ONETIMEONLY",
        },
        headers=normal_user_token_headers,
    )
    assert resp.status_code == 400
    assert "limit" in resp.json()["detail"].lower()


def test_order_event_audit_trail_lifecycle(
    client: TestClient,
    db: Session,
    normal_user_token_headers: dict,
    admin_token_headers: dict,
    sample_product: Product,
):
    """
    Validates complete immutable audit trail generation across the order lifecycle.
    """
    # 1. Place order
    place_resp = client.post(
        "/api/v1/orders/",
        json={
            "shipping_address": "Av. Santander # 54-12, Manizales",
            "items": [{"product_id": sample_product.id, "quantity": 1}],
        },
        headers=normal_user_token_headers,
    )
    assert place_resp.status_code == 201
    order_id = place_resp.json()["id"]

    # 2. Admin marks order as PAID
    patch_resp = client.patch(
        f"/api/v1/orders/{order_id}/status",
        json={"status": "PAID", "notes": "Wire transfer confirmed by finance"},
        headers=admin_token_headers,
    )
    assert patch_resp.status_code == 200

    # 3. Fetch audit events history
    events_resp = client.get(
        f"/api/v1/orders/{order_id}/events",
        headers=normal_user_token_headers,
    )
    assert events_resp.status_code == 200
    events = events_resp.json()
    assert len(events) == 2

    # Initial creation event
    assert events[0]["from_status"] is None
    assert events[0]["to_status"] == "PENDING"
    assert "user:" in events[0]["actor"]

    # Transition to PAID event
    assert events[1]["from_status"] == "PENDING"
    assert events[1]["to_status"] == "PAID"
    assert "admin:" in events[1]["actor"]
    assert "Wire transfer confirmed" in events[1]["notes"]
