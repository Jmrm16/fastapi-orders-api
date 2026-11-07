import logging
import signal
import sys
import time
from typing import Optional, Dict, Any

from app.config import settings
from app.services.queue_service import process_next_task, get_redis_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [QueueWorker] %(message)s",
)
logger = logging.getLogger("queue_worker")

running = True


def handle_shutdown(signum, frame):
    global running
    logger.info("Shutdown signal received. Stopping worker loop...")
    running = False


def run_worker_iteration() -> Optional[Dict[str, Any]]:
    """Runs a single iteration of task pulling and execution."""
    try:
        return process_next_task()
    except Exception as exc:
        logger.error(f"Unexpected worker loop exception: {exc}")
        return None


def main(max_iterations: Optional[int] = None):
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    logger.info("Starting Background Task Worker...")
    logger.info(f"Connected to Redis URL: {settings.REDIS_URL}")
    logger.info(f"Listening on queue: '{settings.REDIS_QUEUE_NAME}' (DLQ: '{settings.REDIS_DLQ_NAME}')")

    get_redis_client()

    iterations = 0
    while running:
        result = run_worker_iteration()
        if result:
            task_id = result.get("id")
            status = result.get("status")
            logger.info(f"Processed task {task_id} -> {status}")
        else:
            time.sleep(0.5)

        iterations += 1
        if max_iterations is not None and iterations >= max_iterations:
            break

    logger.info("Worker stopped gracefully.")


if __name__ == "__main__":
    main()
