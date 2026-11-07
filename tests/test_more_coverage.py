import pytest
import json
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.models.product import Product
from app.models.order import Order, OrderStatus
from app.models.user import User
from app.services.order_service import update_order_status
from app.services.queue_service import (
    enqueue_task,
    dequeue_task,
    process_next_task,
    default_task_handler,
    get_dlq_tasks,
    reprocess_dlq_task,
    reset_queue_state,
)


def test_payment_webhook_order_not_found(client: TestClient):
    resp = client.post(
        "/api/v1/webhooks/payment",
        json={
            "event": "payment.succeeded",
            "order_id": 999999,
            "payment_reference": "ref_999",
            "status": "succeeded",
        },
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_payment_webhook_payment_failed(
    client: TestClient,
    db: Session,
    normal_user: User,
    sample_product: Product,
):
    # Create an order
    order = Order(
        user_id=normal_user.id,
        status=OrderStatus.PENDING,
        subtotal=100.0,
        total_amount=100.0,
        shipping_address="Test Addr",
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    resp = client.post(
        "/api/v1/webhooks/payment",
        json={
            "event": "payment.failed",
            "order_id": order.id,
            "payment_reference": "failed_tx_123",
            "status": "failed",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["order_status"] == "CANCELLED"
    db.refresh(order)
    assert order.status == OrderStatus.CANCELLED


def test_payment_webhook_unhandled_event(
    client: TestClient,
    db: Session,
    normal_user: User,
):
    order = Order(
        user_id=normal_user.id,
        status=OrderStatus.PENDING,
        subtotal=50.0,
        total_amount=50.0,
        shipping_address="Test Addr",
    )
    db.add(order)
    db.commit()

    resp = client.post(
        "/api/v1/webhooks/payment",
        json={
            "event": "customer.created",
            "order_id": order.id,
            "payment_reference": "ref_unused",
            "status": "ignored",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["received"] is True


def test_order_endpoints_error_branches(
    client: TestClient,
    admin_token_headers: dict,
    normal_user_token_headers: dict,
):
    # 1. Cancel non-existent order
    res = client.post("/api/v1/orders/999999/cancel", headers=normal_user_token_headers)
    assert res.status_code == 404

    # 2. Patch status non-existent order
    res = client.patch(
        "/api/v1/orders/999999/status",
        json={"status": "PAID"},
        headers=admin_token_headers,
    )
    assert res.status_code == 404

    # 3. DLQ replay non-existent task
    res = client.post(
        "/api/v1/orders/tasks/dlq/non-existent-task-id/reprocess",
        headers=admin_token_headers,
    )
    assert res.status_code == 404


def test_products_error_branches(
    client: TestClient,
    normal_user_token_headers: dict,
):
    # Non-admin creates product -> 403
    res = client.post(
        "/api/v1/products/",
        json={"sku": "FAIL-SKU", "name": "Fail", "price": 10.0, "stock": 5},
        headers=normal_user_token_headers,
    )
    assert res.status_code == 403

    # Product not found
    res = client.get("/api/v1/products/999999")
    assert res.status_code == 404


def test_queue_service_mocked_redis():
    """Tests queue operations when Redis client is actively connected."""
    mock_redis = MagicMock()
    mock_redis.lpush.return_value = 1
    mock_redis.rpop.return_value = json.dumps({
        "id": "redis-task-1",
        "task_type": "ORDER_STATUS_CHANGED",
        "payload": {"order_id": 10, "new_status": "PAID"},
        "max_retries": 3,
        "retry_count": 0,
        "error_history": [],
    })
    mock_redis.lrange.return_value = [
        json.dumps({
            "id": "dlq-redis-1",
            "task_type": "DEAD_JOB",
            "status": "DEAD_LETTER",
            "payload": {},
            "max_retries": 1,
            "retry_count": 1,
            "error_history": [],
        })
    ]

    with patch("app.services.queue_service._redis_client", mock_redis), \
         patch("app.services.queue_service._use_in_memory_fallback", False):
        # Enqueue via Redis
        enq = enqueue_task("ORDER_STATUS_CHANGED", {"order_id": 10, "new_status": "PAID"})
        assert enq is not None
        mock_redis.lpush.assert_called()

        # Dequeue via Redis
        deq = dequeue_task()
        assert deq is not None
        assert deq["id"] == "redis-task-1"

        # Read DLQ via Redis
        dlq = get_dlq_tasks()
        assert len(dlq) == 1
        assert dlq[0]["id"] == "dlq-redis-1"


def test_queue_service_handlers_and_corrupt_payload():
    reset_queue_state(force_in_memory=True)

    # Handlers for ORDER_STATUS_CHANGED & unhandled
    default_task_handler({"task_type": "ORDER_STATUS_CHANGED", "payload": {"order_id": 1, "new_status": "SHIPPED"}})
    default_task_handler({"task_type": "UNKNOWN_CUSTOM_TASK", "payload": {}})

    # Corrupt payload in queue handled gracefully
    from app.services.queue_service import _in_memory_queues
    _in_memory_queues["orders:tasks"] = ["{INVALID_JSON_CORRUPTED"]
    corrupt_pop = dequeue_task()
    assert corrupt_pop is None
