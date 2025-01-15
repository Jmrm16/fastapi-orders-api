from typing import List, Tuple
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


def create_order(db: Session, user: User, order_in: OrderCreate) -> Order:
    """
    Creates a new order atomically:
    1. Validates all requested products exist and have sufficient inventory.
    2. Decrements product stock.
    3. Calculates item prices and total.
    4. Persists the order and order items in a single transaction.
    """
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
