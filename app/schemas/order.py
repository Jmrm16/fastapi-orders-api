from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field
from app.models.order import OrderStatus
from app.schemas.product import ProductResponse


class OrderItemCreate(BaseModel):
    product_id: int = Field(..., gt=0)
    quantity: int = Field(..., gt=0, le=100, description="Items to order (1 to 100)")


class OrderItemResponse(BaseModel):
    id: int
    product_id: int
    quantity: int
    unit_price: float
    subtotal: float
    product: Optional[ProductResponse] = None

    model_config = ConfigDict(from_attributes=True)


class OrderCreate(BaseModel):
    shipping_address: str = Field(..., min_length=5, max_length=512)
    items: List[OrderItemCreate] = Field(..., min_length=1, description="Order must contain at least one item")
    coupon_code: Optional[str] = Field(default=None, max_length=32, description="Optional promo code for discount")


class OrderStatusUpdate(BaseModel):
    status: OrderStatus
    notes: Optional[str] = Field(default=None, max_length=500, description="Reason or note for status transition")


class OrderEventResponse(BaseModel):
    id: int
    order_id: int
    from_status: Optional[str] = None
    to_status: str
    actor: str
    notes: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OrderResponse(BaseModel):
    id: int
    user_id: int
    status: OrderStatus
    subtotal: float = 0.0
    discount_amount: float = 0.0
    total_amount: float
    shipping_address: str
    idempotency_key: Optional[str] = None
    coupon_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    items: List[OrderItemResponse] = []
    events: List[OrderEventResponse] = []

    model_config = ConfigDict(from_attributes=True)


class TopSellingProduct(BaseModel):
    product_id: int
    product_name: str
    units_sold: int
    total_revenue: float


class OrderAnalyticsSummary(BaseModel):
    total_orders: int
    total_revenue: float
    average_order_value: float
    status_breakdown: dict[str, int]
    top_selling_products: List[TopSellingProduct] = []
