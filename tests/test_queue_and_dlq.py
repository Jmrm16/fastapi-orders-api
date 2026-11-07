import pytest
from fastapi.testclient import TestClient
from app.services.queue_service import (
    enqueue_task,
    dequeue_task,
    process_next_task,
    get_dlq_tasks,
    reprocess_dlq_task,
    reset_queue_state,
)
from app.models.user import User


@pytest.fixture(autouse=True)
def setup_test_queue():
    """Ensure in-memory fallback is active and clean for each test."""
    reset_queue_state(force_in_memory=True)
    yield
    reset_queue_state(force_in_memory=True)


def test_enqueue_and_dequeue_task_fifo():
    task1 = enqueue_task("SEND_INVOICE", {"order_id": 101, "email": "customer1@test.com"})
    task2 = enqueue_task("SEND_INVOICE", {"order_id": 102, "email": "customer2@test.com"})

    # FIFO order: task1 was queued first
    popped1 = dequeue_task()
    assert popped1 is not None
    assert popped1["id"] == task1["id"]
    assert popped1["payload"]["order_id"] == 101

    popped2 = dequeue_task()
    assert popped2 is not None
    assert popped2["id"] == task2["id"]
    assert popped2["payload"]["order_id"] == 102

    # Queue should now be empty
    assert dequeue_task() is None


def test_task_success_processing():
    enqueue_task("ORDER_CREATED", {"order_id": 55, "total_amount": 199.99})

    processed = process_next_task()
    assert processed is not None
    assert processed["status"] == "COMPLETED"
    assert "completed_at" in processed
    assert processed["retry_count"] == 0

    # DLQ should remain completely empty
    assert len(get_dlq_tasks()) == 0


def test_task_retries_and_dead_letter_queue_escalation():
    """
    Verifies that a failing task is retried up to MAX_TASK_RETRIES (3),
    and upon exhausting retries, is automatically routed to the Dead Letter Queue (DLQ).
    """
    task = enqueue_task(
        "SIMULATE_FAILURE",
        {"order_id": 999, "action": "critical_sync"},
        max_retries=3,
    )
    task_id = task["id"]

    # Attempt 1 -> Failure -> Re-enqueued with retry_count=1
    res1 = process_next_task()
    assert res1["status"] == "RETRYING"
    assert res1["retry_count"] == 1
    assert len(get_dlq_tasks()) == 0

    # Attempt 2 -> Failure -> Re-enqueued with retry_count=2
    res2 = process_next_task()
    assert res2["status"] == "RETRYING"
    assert res2["retry_count"] == 2
    assert len(get_dlq_tasks()) == 0

    # Attempt 3 -> Final Failure -> Transferred to Dead Letter Queue (DLQ)
    res3 = process_next_task()
    assert res3["status"] == "DEAD_LETTER"
    assert res3["retry_count"] == 3
    assert "Simulated processing exception" in res3["final_error"]

    # Verify task is now present in DLQ
    dlq_items = get_dlq_tasks()
    assert len(dlq_items) == 1
    assert dlq_items[0]["id"] == task_id
    assert dlq_items[0]["status"] == "DEAD_LETTER"
    assert len(dlq_items[0]["error_history"]) == 3


def test_dlq_task_reprocessing_and_recovery():
    """
    Verifies that an administrator can replay/reprocess a failed task from the DLQ.
    """
    task = enqueue_task(
        "SIMULATE_FAILURE",
        {"order_id": 888},
        max_retries=1,
    )
    task_id = task["id"]

    # Fail and send directly to DLQ
    failed_task = process_next_task()
    assert failed_task["status"] == "DEAD_LETTER"
    assert len(get_dlq_tasks()) == 1

    # Administrator requests DLQ replay
    reprocess_success = reprocess_dlq_task(task_id=task_id)
    assert reprocess_success is True

    # DLQ should now be empty and task back on the active processing queue
    assert len(get_dlq_tasks()) == 0

    # Dequeue from active queue with reset retry count
    requeued = dequeue_task()
    assert requeued is not None
    assert requeued["id"] == task_id
    assert requeued["retry_count"] == 0
    assert requeued["status"] == "REQUEUED"


def test_admin_dlq_api_endpoints(
    client: TestClient,
    admin_token_headers: dict,
    normal_user_token_headers: dict,
):
    """
    Tests GET /api/v1/orders/tasks/dlq and POST /api/v1/orders/tasks/dlq/{task_id}/reprocess.
    Ensures RBAC protects DLQ endpoints against non-admin users.
    """
    # Push a failing task to DLQ
    enqueue_task("SIMULATE_FAILURE", {"order_id": 777}, max_retries=1)
    failed = process_next_task()
    assert failed["status"] == "DEAD_LETTER"
    task_id = failed["id"]

    # 1. Non-admin user receives 403 Forbidden
    forbidden_resp = client.get(
        "/api/v1/orders/tasks/dlq",
        headers=normal_user_token_headers,
    )
    assert forbidden_resp.status_code == 403

    # 2. Admin successfully lists DLQ items
    admin_resp = client.get(
        "/api/v1/orders/tasks/dlq",
        headers=admin_token_headers,
    )
    assert admin_resp.status_code == 200
    dlq_data = admin_resp.json()
    assert len(dlq_data) == 1
    assert dlq_data[0]["id"] == task_id
    assert dlq_data[0]["status"] == "DEAD_LETTER"

    # 3. Admin replays DLQ task
    reprocess_resp = client.post(
        f"/api/v1/orders/tasks/dlq/{task_id}/reprocess",
        headers=admin_token_headers,
    )
    assert reprocess_resp.status_code == 200
    assert f"successfully requeued" in reprocess_resp.json()["message"]

    # 4. DLQ is now empty
    empty_resp = client.get(
        "/api/v1/orders/tasks/dlq",
        headers=admin_token_headers,
    )
    assert empty_resp.status_code == 200
    assert len(empty_resp.json()) == 0
