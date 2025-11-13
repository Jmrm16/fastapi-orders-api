from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.order import Order, OrderStatus
from app.services.order_service import update_order_status
from app.core.exceptions import OrderStateTransitionException

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


class PaymentWebhookPayload(BaseModel):
    event: str
    order_id: int
    payment_reference: str
    status: str  # e.g. "succeeded", "failed"


@router.post("/payment", status_code=status.HTTP_200_OK)
def handle_payment_webhook(payload: PaymentWebhookPayload, db: Session = Depends(get_db)):
    """
    Webhook endpoint to receive async notifications from payment processors (Stripe/PayPal/MercadoPago).
    """
    order = db.query(Order).filter(Order.id == payload.order_id).first()
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order {payload.order_id} not found"
        )

    if payload.event == "payment.succeeded" and payload.status == "succeeded":
        try:
            update_order_status(db=db, order=order, new_status=OrderStatus.PAID)
            return {"received": True, "order_status": "PAID"}
        except OrderStateTransitionException as exc:
            return {"received": True, "warning": exc.message}

    elif payload.event == "payment.failed":
        try:
            update_order_status(db=db, order=order, new_status=OrderStatus.CANCELLED)
            return {"received": True, "order_status": "CANCELLED"}
        except OrderStateTransitionException:
            return {"received": True, "warning": "Order was not cancelled"}

    return {"received": True}
