from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field
from app.models.coupon import DiscountType


class CouponBase(BaseModel):
    code: str = Field(..., min_length=3, max_length=32, description="Unique promo code uppercase")
    discount_type: DiscountType = Field(default=DiscountType.PERCENTAGE)
    discount_value: float = Field(..., gt=0, description="Percentage (e.g. 15 for 15%) or flat amount in USD")
    min_order_amount: float = Field(default=0.0, ge=0)
    max_uses: Optional[int] = Field(default=None, gt=0)
    valid_until: Optional[datetime] = None
    is_active: bool = True


class CouponCreate(CouponBase):
    pass


class CouponResponse(CouponBase):
    id: int
    times_used: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CouponValidateResponse(BaseModel):
    code: str
    is_valid: bool
    discount_type: DiscountType
    discount_value: float
    estimated_discount: float
    message: str
