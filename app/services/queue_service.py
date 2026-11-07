import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
import redis

from app.config import settings

logger = logging.getLogger("fastapi_orders.queue")

_redis_client: Optional[redis.Redis] = None
_in_memory_queues: Dict[str, List[str]] = {}
_use_in_memory_fallback: bool = False


def get_redis_client() -> Optional[redis.Redis]:
    """
    Returns an active Redis client connection.
    If Redis cannot be reached (e.g. local development without Docker),
    flags the queue service to use the deterministic in-memory queue fallback.
    """
    global _redis_client, _use_in_memory_fallback
    if _use_in_memory_fallback:
        return None

    if _redis_client is None:
        try:
            client = redis.Redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_timeout=1.5,
                socket_connect_timeout=1.5,
            )
            # Ping to verify connectivity
            client.ping()
            _redis_client = client
            logger.info(f"Connected to Redis at {settings.REDIS_URL}")
        except Exception as e:
            logger.warning(
                f"Redis unavailable ({e}). Falling back to in-memory queue engine."
            )
            _use_in_memory_fallback = True
            _redis_client = None

    return _redis_client


def reset_queue_state(force_in_memory: bool = False) -> None:
    """Helper for testing: clears in-memory structures and optionally forces in-memory mode."""
    global _redis_client, _use_in_memory_fallback, _in_memory_queues
    _in_memory_queues.clear()
    if force_in_memory:
        _use_in_memory_fallback = True
        _redis_client = None
    else:
        _use_in_memory_fallback = False
        _redis_client = None


def enqueue_task(
    task_type: str,
    payload: Dict[str, Any],
    queue_name: Optional[str] = None,
    max_retries: Optional[int] = None,
    task_id: Optional[str] = None,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Serializes and enqueues an asynchronous task to the Redis task queue.
    """
    queue = queue_name or settings.REDIS_QUEUE_NAME
    tid = task_id or str(uuid.uuid4())
    task_record = {
        "id": tid,
        "task_type": task_type,
        "payload": payload,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": status or "QUEUED",
        "retry_count": 0,
        "max_retries": max_retries or settings.MAX_TASK_RETRIES,
        "error_history": [],
    }
    raw_payload = json.dumps(task_record)

    client = get_redis_client()
    if client:
        try:
            client.lpush(queue, raw_payload)
            logger.info(f"Enqueued task {task_id} [{task_type}] to Redis queue '{queue}'")
            return task_record
        except Exception as exc:
            logger.error(f"Failed to LPUSH to Redis: {exc}. Using in-memory fallback.")

    # Fallback to in-memory list
    if queue not in _in_memory_queues:
        _in_memory_queues[queue] = []
    _in_memory_queues[queue].insert(0, raw_payload)
    logger.info(f"Enqueued task {task_id} [{task_type}] to in-memory queue '{queue}'")
    return task_record


def dequeue_task(queue_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Pops the oldest task from the queue (FIFO: RPOP).
    """
    queue = queue_name or settings.REDIS_QUEUE_NAME
    client = get_redis_client()
    raw_data: Optional[str] = None

    if client:
        try:
            raw_data = client.rpop(queue)
        except Exception as exc:
            logger.error(f"Failed to RPOP from Redis: {exc}")

    if raw_data is None:
        q_list = _in_memory_queues.get(queue, [])
        if q_list:
            raw_data = q_list.pop()

    if raw_data:
        try:
            return json.loads(raw_data)
        except json.JSONDecodeError:
            logger.error(f"Corrupt JSON payload popped from queue '{queue}': {raw_data}")
            return None

    return None


def send_to_dead_letter_queue(
    task: Dict[str, Any],
    final_error: str,
    dlq_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Routes a failed task exceeding max_retries into the Dead Letter Queue (DLQ).
    Enriches the record with diagnostic failure metadata.
    """
    dlq = dlq_name or settings.REDIS_DLQ_NAME
    task["failed_at"] = datetime.now(timezone.utc).isoformat()
    task["final_error"] = final_error
    task["status"] = "DEAD_LETTER"

    raw_payload = json.dumps(task)
    client = get_redis_client()
    if client:
        try:
            client.lpush(dlq, raw_payload)
            logger.warning(
                f"Task {task['id']} [{task['task_type']}] permanently moved to DLQ '{dlq}'. Reason: {final_error}"
            )
            return task
        except Exception as exc:
            logger.error(f"Failed to push task to Redis DLQ: {exc}")

    if dlq not in _in_memory_queues:
        _in_memory_queues[dlq] = []
    _in_memory_queues[dlq].insert(0, raw_payload)
    logger.warning(
        f"Task {task['id']} [{task['task_type']}] moved to in-memory DLQ '{dlq}'"
    )
    return task


def process_next_task(
    handler: Optional[Callable[[Dict[str, Any]], None]] = None,
    queue_name: Optional[str] = None,
    dlq_name: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Pulls a task from the queue and executes the handler.
    If the handler succeeds, returns the completed task.
    If the handler raises an Exception:
      - Increments retry_count.
      - If retry_count < max_retries: Re-enqueues task for retry.
      - If retry_count >= max_retries: Routes task to the Dead Letter Queue (DLQ).
    """
    queue = queue_name or settings.REDIS_QUEUE_NAME
    dlq = dlq_name or settings.REDIS_DLQ_NAME

    task = dequeue_task(queue)
    if not task:
        return None

    task_id = task.get("id")
    task_type = task.get("task_type")

    try:
        if handler:
            handler(task)
        else:
            default_task_handler(task)

        task["status"] = "COMPLETED"
        task["completed_at"] = datetime.now(timezone.utc).isoformat()
        logger.info(f"Task {task_id} [{task_type}] executed successfully.")
        return task

    except Exception as exc:
        error_msg = str(exc)
        task["retry_count"] = task.get("retry_count", 0) + 1
        task["error_history"].append({
            "retry": task["retry_count"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": error_msg,
        })
        logger.warning(
            f"Task {task_id} failed attempt {task['retry_count']}/{task.get('max_retries')}: {error_msg}"
        )

        if task["retry_count"] >= task.get("max_retries", settings.MAX_TASK_RETRIES):
            # Exhausted all retries -> Transfer to Dead Letter Queue (DLQ)
            return send_to_dead_letter_queue(task, final_error=error_msg, dlq_name=dlq)
        else:
            # Re-enqueue for retry
            raw_payload = json.dumps(task)
            client = get_redis_client()
            if client:
                try:
                    client.lpush(queue, raw_payload)
                except Exception:
                    if queue not in _in_memory_queues:
                        _in_memory_queues[queue] = []
                    _in_memory_queues[queue].insert(0, raw_payload)
            else:
                if queue not in _in_memory_queues:
                    _in_memory_queues[queue] = []
                _in_memory_queues[queue].insert(0, raw_payload)

            task["status"] = "RETRYING"
            return task


def default_task_handler(task: Dict[str, Any]) -> None:
    """Default processing logic for known order task events."""
    task_type = task.get("task_type")
    payload = task.get("payload", {})

    if task_type == "ORDER_CREATED":
        order_id = payload.get("order_id")
        total = payload.get("total_amount")
        logger.info(f"[Worker] Processing post-order creation: Order #{order_id}, Total: ${total}")
    elif task_type == "ORDER_STATUS_CHANGED":
        order_id = payload.get("order_id")
        to_status = payload.get("new_status")
        logger.info(f"[Worker] Syncing inventory/notification for Order #{order_id} -> {to_status}")
    elif task_type == "SIMULATE_FAILURE":
        raise RuntimeError("Simulated processing exception for retry & DLQ verification")
    else:
        logger.info(f"[Worker] Unhandled task type: {task_type}")


def get_dlq_tasks(dlq_name: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """Returns list of failed tasks currently held in the Dead Letter Queue."""
    dlq = dlq_name or settings.REDIS_DLQ_NAME
    client = get_redis_client()
    raw_list: List[str] = []

    if client:
        try:
            raw_list = client.lrange(dlq, 0, limit - 1)
        except Exception as exc:
            logger.error(f"Failed to LRANGE from Redis DLQ: {exc}")

    if not raw_list:
        raw_list = list(reversed(_in_memory_queues.get(dlq, [])))[:limit]

    results: List[Dict[str, Any]] = []
    for item in raw_list:
        try:
            results.append(json.loads(item))
        except json.JSONDecodeError:
            continue
    return results


def reprocess_dlq_task(task_id: str, dlq_name: Optional[str] = None, queue_name: Optional[str] = None) -> bool:
    """
    Pulls a specific task from DLQ, resets its retry count, and puts it back on the active queue.
    """
    dlq = dlq_name or settings.REDIS_DLQ_NAME
    queue = queue_name or settings.REDIS_QUEUE_NAME

    tasks = get_dlq_tasks(dlq_name=dlq, limit=500)
    target_task = None
    for t in tasks:
        if t.get("id") == task_id:
            target_task = t
            break

    if not target_task:
        return False

    # Remove from DLQ
    client = get_redis_client()
    if client:
        try:
            client.lrem(dlq, 1, json.dumps(target_task))
        except Exception:
            pass

    if dlq in _in_memory_queues:
        _in_memory_queues[dlq] = [
            raw for raw in _in_memory_queues[dlq]
            if json.loads(raw).get("id") != task_id
        ]

    # Reset retry metadata and re-enqueue
    target_task["retry_count"] = 0
    target_task["status"] = "REQUEUED"
    target_task["requeued_at"] = datetime.now(timezone.utc).isoformat()
    enqueue_task(
        task_type=target_task["task_type"],
        payload=target_task["payload"],
        queue_name=queue,
        max_retries=target_task.get("max_retries"),
        task_id=target_task.get("id"),
        status="REQUEUED",
    )
    return True
