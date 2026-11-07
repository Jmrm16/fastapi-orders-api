import pytest
from unittest.mock import patch, MagicMock
from app.tasks.worker import run_worker_iteration, handle_shutdown, main
from app.services.queue_service import enqueue_task, reset_queue_state
import app.tasks.worker as worker_module


@pytest.fixture(autouse=True)
def setup_worker_queue():
    reset_queue_state(force_in_memory=True)
    worker_module.running = True
    yield
    reset_queue_state(force_in_memory=True)
    worker_module.running = True


def test_worker_iteration_with_task():
    enqueue_task("ORDER_CREATED", {"order_id": 1, "total_amount": 50.0})
    res = run_worker_iteration()
    assert res is not None
    assert res["status"] == "COMPLETED"


def test_worker_iteration_empty_queue():
    res = run_worker_iteration()
    assert res is None


def test_worker_iteration_exception_handled():
    with patch("app.tasks.worker.process_next_task", side_effect=Exception("Simulated worker error")):
        res = run_worker_iteration()
        assert res is None


def test_worker_handle_shutdown():
    worker_module.running = True
    handle_shutdown(None, None)
    assert worker_module.running is False


def test_worker_main_loop_with_max_iterations():
    enqueue_task("ORDER_CREATED", {"order_id": 99, "total_amount": 10.0})
    main(max_iterations=2)
    # Ran without crashing
