from typing import List, Tuple, Optional, Dict, Any
from sqlalchemy import func, desc
from sqlalchemy.orm import Session
from app.models.order import Order, OrderItem, OrderStatus
from app.models.product import Product
from app.models.user import User
from app.schemas.order import OrderCreate
from app.core.exceptions import (
    InsufficientStockException,
    EntityNotFoundException,
    OrderStateTransitionException,
)

# Allowed order lifecycle transitions
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
    Creates a new order atomically:
    1. Checks idempotency key to prevent double-charging on duplicate requests.
    2. Validates all requested products exist and have sufficient inventory.
    3. Decrements product stock.
    4. Calculates item prices and total.
    5. Persists the order and order items in a single transaction.
    """
    # 1. Idempotency Guard (e.g. Stripe-grade retry protection)
    if idempotency_key:
        existing_order = (
            db.query(Order)
            .filter(Order.idempotency_key == idempotency_key)
            .first()
        )
        if existing_order:
            return existing_order

    # Group and validate requested items
    requested_product_ids = [item.product_id for item in order_in.items]
    products = db.query(Product).filter(Product.id.in_(requested_product_ids)).all()
    products_by_id = {p.id: p for p in products}

    # Verify every product exists and is active
    for item in order_in.items:
        product = products_by_id.get(item.product_id)
        if not product or not product.is_active:
            raise EntityNotFoundException("Product", item.product_id)
        if product.stock < item.quantity:
            raise InsufficientStockException(
                product_name=product.name,
                available=product.stock,
                requested=item.quantity
            )

    # All validations passed; instantiate order
    order = Order(
        user_id=user.id,
        status=OrderStatus.PENDING,
        shipping_address=order_in.shipping_address,
        idempotency_key=idempotency_key,
        total_amount=0.0,
    )
    db.add(order)
    db.flush()  # Generates order.id for foreign keys

    total = 0.0
    for item in order_in.items:
        product = products_by_id[item.product_id]
        
        # Atomically reserve inventory
        product.stock -= item.quantity

        order_item = OrderItem(
            order_id=order.id,
            product_id=product.id,
            quantity=item.quantity,
            unit_price=product.price,
        )
        total += order_item.subtotal
        db.add(order_item)

    order.total_amount = round(total, 2)
    db.commit()
    db.refresh(order)
    return order


def update_order_status(db: Session, order: Order, new_status: OrderStatus) -> Order:
    """
    Updates the status of an order obeying the state machine.
    If the order is cancelled, inventory is automatically restored.
    """
    if order.status == new_status:
        return order

    allowed = ALLOWED_TRANSITIONS.get(order.status, set())
    if new_status not in allowed:
        raise OrderStateTransitionException(
            current_status=order.status.value,
            target_status=new_status.value
        )

    # Restock inventory if cancelled
    if new_status == OrderStatus.CANCELLED:
        for item in order.items:
            product = db.query(Product).filter(Product.id == item.product_id).first()
            if product:
                product.stock += item.quantity

    order.status = new_status
    db.commit()
    db.refresh(order)
    return order


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

    # Non-cancelled revenue
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

    # Status breakdown
    status_counts = (
        db.query(Order.status, func.count(Order.id))
        .group_by(Order.status)
        .all()
    )
    status_breakdown = {status.value: 0 for status in OrderStatus}
    for st, count in status_counts:
        status_key = st.value if hasattr(st, "value") else str(st)
        status_breakdown[status_key] = count

    # Top selling products
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
