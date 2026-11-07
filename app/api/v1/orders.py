from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.models.order import Order, OrderStatus
from app.schemas.order import (
    OrderCreate,
    OrderResponse,
    OrderStatusUpdate,
    OrderAnalyticsSummary,
    OrderEventResponse,
)
from app.services.order_service import (
    create_order,
    update_order_status,
    get_order_events,
    get_order_analytics_summary,
)
from app.services.queue_service import get_dlq_tasks, reprocess_dlq_task
from app.core.security import get_current_active_user, get_current_admin_user
from app.core.exceptions import (
    InsufficientStockException,
    EntityNotFoundException,
    OrderStateTransitionException,
    CouponValidationException,
)

router = APIRouter(prefix="/orders", tags=["Orders"])


@router.post("/", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
def place_order(
    order_in: OrderCreate,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Places a new customer order and atomically reserves product inventory.
    Supports promo codes and optional 'Idempotency-Key' header for duplicate request protection.
    """
    try:
        order = create_order(
            db=db,
            user=current_user,
            order_in=order_in,
            idempotency_key=idempotency_key,
        )
        return order
    except EntityNotFoundException as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message)
    except (InsufficientStockException, CouponValidationException) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message)


@router.get("/analytics/summary", response_model=OrderAnalyticsSummary)
def get_orders_analytics(
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin_user),
):
    """
    Computes global business analytics and revenue summary (Administrator only).
    Calculates total GMV, order volume, status breakdown and top-selling items.
    """
    return get_order_analytics_summary(db=db)


@router.get("/", response_model=List[OrderResponse])
def get_user_orders(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Lists all orders placed by the current user (or all if admin)."""
    if current_user.is_admin:
        orders = db.query(Order).order_by(Order.created_at.desc()).all()
    else:
        orders = (
            db.query(Order)
            .filter(Order.user_id == current_user.id)
            .order_by(Order.created_at.desc())
            .all()
        )
    return orders


@router.get("/{order_id}", response_model=OrderResponse)
def get_order_by_id(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Retrieves an order by ID (only accessible by order owner or admin)."""
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    if not current_user.is_admin and order.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return order


@router.get("/{order_id}/events", response_model=List[OrderEventResponse])
def get_order_event_history(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Retrieves immutable audit trail of state transitions for the specified order."""
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    if not current_user.is_admin and order.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return get_order_events(db=db, order_id=order_id)


@router.post("/{order_id}/cancel", response_model=OrderResponse)
def cancel_customer_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Cancels an order and automatically releases the reserved inventory."""
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    if not current_user.is_admin and order.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    try:
        updated = update_order_status(
            db=db,
            order=order,
            new_status=OrderStatus.CANCELLED,
            actor=f"user:{current_user.id}",
            notes="Order cancelled by customer",
        )
        return updated
    except OrderStateTransitionException as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message)


@router.patch("/{order_id}/status", response_model=OrderResponse)
def set_order_status(
    order_id: int,
    status_update: OrderStatusUpdate,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin_user),
):
    """Updates order status via fulfillment state machine (Administrator only)."""
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    try:
        updated = update_order_status(
            db=db,
            order=order,
            new_status=status_update.status,
            actor=f"admin:{_admin.id}",
            notes=status_update.notes,
        )
        return updated
    except OrderStateTransitionException as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message)


@router.get("/tasks/dlq", response_model=List[dict])
def list_dead_letter_queue_tasks(
    limit: int = 50,
    _admin: User = Depends(get_current_admin_user),
):
    """
    Retrieves poisoned and failed asynchronous tasks currently residing in the Redis Dead Letter Queue (DLQ).
    Requires administrative permissions.
    """
    return get_dlq_tasks(limit=limit)


@router.post("/tasks/dlq/{task_id}/reprocess", status_code=status.HTTP_200_OK)
def replay_dead_letter_queue_task(
    task_id: str,
    _admin: User = Depends(get_current_admin_user),
):
    """
    Requeues a failed task from the Dead Letter Queue back into the active processing queue.
    Requires administrative permissions.
    """
    success = reprocess_dlq_task(task_id=task_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task '{task_id}' not found in Dead Letter Queue",
        )
    return {"message": f"Task '{task_id}' successfully requeued for execution", "task_id": task_id}
