from typing import List, Tuple, Optional, Dict, Any
from sqlalchemy import func, desc
from sqlalchemy.orm import Session
from app.models.order import Order, OrderItem, OrderStatus, OrderEvent
from app.models.product import Product
from app.models.user import User
from app.models.coupon import Coupon
from app.schemas.order import OrderCreate
from app.core.exceptions import (
    InsufficientStockException,
    EntityNotFoundException,
    OrderStateTransitionException,
    CouponValidationException,
)

# Allowed order lifecycle state transitions
ALLOWED_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.PENDING: {OrderStatus.PAID, OrderStatus.CANCELLED},
    OrderStatus.PAID: {OrderStatus.PROCESSING, OrderStatus.CANCELLED},
    OrderStatus.PROCESSING: {OrderStatus.SHIPPED, OrderStatus.CANCELLED},
    OrderStatus.SHIPPED: set(),  # Terminal state
    OrderStatus.CANCELLED: set(),  # Terminal state
}


def create_order(
    db: Session,
    user: User,
    order_in: OrderCreate,
    idempotency_key: Optional[str] = None,
) -> Order:
    """
    Creates an order atomically with race-condition prevention:
    1. Idempotency check prevents duplicate submission on client retries.
    2. Validates coupon constraints against the calculated subtotal.
    3. Atomically reserves product inventory using conditional database updates
       to strictly prevent overselling under high concurrency.
    4. Calculates discounts, item breakdowns, and net total.
    5. Records initial lifecycle audit event.
    """
    # 1. Idempotency Guard
    if idempotency_key:
        existing_order = (
            db.query(Order)
            .filter(Order.idempotency_key == idempotency_key)
            .first()
        )
        if existing_order:
            return existing_order

    # 2. Pre-fetch and validate products exist and are active
    requested_product_ids = [item.product_id for item in order_in.items]
    products = db.query(Product).filter(Product.id.in_(requested_product_ids)).all()
    products_by_id = {p.id: p for p in products}

    for item in order_in.items:
        p = products_by_id.get(item.product_id)
        if not p or not p.is_active:
            raise EntityNotFoundException("Product", item.product_id)

    # 3. Calculate subtotal before discounts
    subtotal = sum(
        products_by_id[item.product_id].price * item.quantity
        for item in order_in.items
    )
    subtotal = round(subtotal, 2)

    # 4. Coupon validation and discount calculation
    coupon: Optional[Coupon] = None
    discount_amount = 0.0
    if order_in.coupon_code:
        coupon = (
            db.query(Coupon)
            .filter(Coupon.code == order_in.coupon_code.strip().upper())
            .first()
        )
        if not coupon:
            raise CouponValidationException(f"Coupon '{order_in.coupon_code}' does not exist")
        
        is_valid, reason = coupon.is_valid(subtotal)
        if not is_valid:
            raise CouponValidationException(reason)

        discount_amount = coupon.calculate_discount(subtotal)
        coupon.times_used += 1

    net_total = round(max(0.0, subtotal - discount_amount), 2)

    # 5. Atomic inventory reservation:
    # Under PostgreSQL, uses pessimistic row locking (SELECT ... FOR UPDATE via with_for_update())
    # to serialize concurrent transactions and prevent overselling under high concurrency.
    # On SQLite (used for rapid isolated unit testing), executes atomic conditional updates (WHERE stock >= requested).
    for item in order_in.items:
        if db.bind and getattr(db.bind.dialect, "name", "") == "postgresql":
            # PostgreSQL Pessimistic Row Lock with fresh database state
            locked_product = (
                db.query(Product)
                .filter(Product.id == item.product_id)
                .with_for_update()
                .populate_existing()
                .first()
            )
            if not locked_product or not locked_product.is_active or locked_product.stock < item.quantity:
                avail = locked_product.stock if locked_product else 0
                name = locked_product.name if locked_product else f"Product #{item.product_id}"
                raise InsufficientStockException(
                    product_name=name,
                    available=avail,
                    requested=item.quantity,
                )
            locked_product.stock -= item.quantity
        else:
            # SQLite Atomic Conditional Update fallback
            rows_updated = (
                db.query(Product)
                .filter(
                    Product.id == item.product_id,
                    Product.stock >= item.quantity,
                    Product.is_active.is_(True),
                )
                .update(
                    {Product.stock: Product.stock - item.quantity},
                    synchronize_session="fetch",
                )
            )
            if rows_updated == 0:
                # Atomic update failed: insufficient inventory
                current_p = db.query(Product).filter(Product.id == item.product_id).first()
                avail = current_p.stock if current_p else 0
                name = current_p.name if current_p else f"Product #{item.product_id}"
                raise InsufficientStockException(
                    product_name=name,
                    available=avail,
                    requested=item.quantity,
                )

    # 6. Create order record
    order = Order(
        user_id=user.id,
        status=OrderStatus.PENDING,
        subtotal=subtotal,
        discount_amount=discount_amount,
        total_amount=net_total,
        shipping_address=order_in.shipping_address,
        idempotency_key=idempotency_key,
        coupon_id=coupon.id if coupon else None,
    )
    db.add(order)
    db.flush()

    # 7. Create line items
    for item in order_in.items:
        p = products_by_id[item.product_id]
        order_item = OrderItem(
            order_id=order.id,
            product_id=p.id,
            quantity=item.quantity,
            unit_price=p.price,
        )
        db.add(order_item)

    # 8. Record audit event
    creation_event = OrderEvent(
        order_id=order.id,
        from_status=None,
        to_status=OrderStatus.PENDING.value,
        actor=f"user:{user.id}",
        notes="Order placed by customer",
    )
    db.add(creation_event)

    db.commit()
    db.refresh(order)

    # 9. Asynchronously enqueue post-order creation event to Redis Task Queue
    try:
        from app.services.queue_service import enqueue_task
        enqueue_task(
            task_type="ORDER_CREATED",
            payload={
                "order_id": order.id,
                "user_id": user.id,
                "total_amount": float(order.total_amount),
                "shipping_address": order.shipping_address,
            },
        )
    except Exception:
        pass

    return order


def update_order_status(
    db: Session,
    order: Order,
    new_status: OrderStatus,
    actor: str = "system",
    notes: Optional[str] = None,
) -> Order:
    """
    Transitions order to a new state and writes an immutable audit record.
    If the order is cancelled, stock is restored and coupon usage decremented.
    """
    if order.status == new_status:
        return order

    allowed = ALLOWED_TRANSITIONS.get(order.status, set())
    if new_status not in allowed:
        raise OrderStateTransitionException(
            current_status=order.status.value,
            target_status=new_status.value,
        )

    old_status = order.status

    # Restock inventory and revert coupon usage if cancelled
    if new_status == OrderStatus.CANCELLED:
        for item in order.items:
            db.query(Product).filter(Product.id == item.product_id).update(
                {Product.stock: Product.stock + item.quantity},
                synchronize_session="fetch",
            )
        if order.coupon_id:
            coupon = db.query(Coupon).filter(Coupon.id == order.coupon_id).first()
            if coupon:
                coupon.times_used = max(0, coupon.times_used - 1)

    order.status = new_status

    # Record lifecycle transition event
    audit_event = OrderEvent(
        order_id=order.id,
        from_status=old_status.value,
        to_status=new_status.value,
        actor=actor,
        notes=notes or f"Status changed from {old_status.value} to {new_status.value}",
    )
    db.add(audit_event)

    db.commit()
    db.refresh(order)

    # Dispatch status change event to Redis Task Queue
    try:
        from app.services.queue_service import enqueue_task
        enqueue_task(
            task_type="ORDER_STATUS_CHANGED",
            payload={
                "order_id": order.id,
                "old_status": old_status.value,
                "new_status": new_status.value,
                "actor": actor,
            },
        )
    except Exception:
        pass

    return order


def get_order_events(db: Session, order_id: int) -> List[OrderEvent]:
    """Retrieves full audit log history for an order in chronological order."""
    return (
        db.query(OrderEvent)
        .filter(OrderEvent.order_id == order_id)
        .order_by(OrderEvent.created_at.asc())
        .all()
    )


def get_order_analytics_summary(db: Session) -> Dict[str, Any]:
    """
    Computes global order analytics and financial metrics:
    - Total order count
    - Gross Merchandise Value (excluding CANCELLED)
    - Average Order Value
    - Status breakdown counts
    - Top selling products by units and revenue
    """
    total_orders = db.query(func.count(Order.id)).scalar() or 0

    revenue_res = (
        db.query(func.coalesce(func.sum(Order.total_amount), 0.0))
        .filter(Order.status != OrderStatus.CANCELLED)
        .scalar()
    )
    total_revenue = round(float(revenue_res or 0.0), 2)

    valid_orders_count = (
        db.query(func.count(Order.id))
        .filter(Order.status != OrderStatus.CANCELLED)
        .scalar()
        or 0
    )
    average_order_value = (
        round(total_revenue / valid_orders_count, 2) if valid_orders_count > 0 else 0.0
    )

    status_counts = (
        db.query(Order.status, func.count(Order.id))
        .group_by(Order.status)
        .all()
    )
    status_breakdown = {status.value: 0 for status in OrderStatus}
    for st, count in status_counts:
        status_key = st.value if hasattr(st, "value") else str(st)
        status_breakdown[status_key] = count

    top_products_query = (
        db.query(
            Product.id,
            Product.name,
            func.sum(OrderItem.quantity).label("units_sold"),
            func.sum(OrderItem.quantity * OrderItem.unit_price).label("revenue"),
        )
        .join(OrderItem, Product.id == OrderItem.product_id)
        .join(Order, Order.id == OrderItem.order_id)
        .filter(Order.status != OrderStatus.CANCELLED)
        .group_by(Product.id, Product.name)
        .order_by(desc("units_sold"))
        .limit(5)
        .all()
    )

    top_selling = [
        {
            "product_id": p_id,
            "product_name": p_name,
            "units_sold": int(units or 0),
            "total_revenue": round(float(rev or 0.0), 2),
        }
        for p_id, p_name, units, rev in top_products_query
    ]

    return {
        "total_orders": total_orders,
        "total_revenue": total_revenue,
        "average_order_value": average_order_value,
        "status_breakdown": status_breakdown,
        "top_selling_products": top_selling,
    }
