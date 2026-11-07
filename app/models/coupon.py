import enum
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Enum
from app.database import Base


class DiscountType(str, enum.Enum):
    PERCENTAGE = "PERCENTAGE"
    FIXED = "FIXED"


class Coupon(Base):
    __tablename__ = "coupons"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(32), unique=True, index=True, nullable=False)
    discount_type = Column(Enum(DiscountType), nullable=False, default=DiscountType.PERCENTAGE)
    discount_value = Column(Float, nullable=False)
    min_order_amount = Column(Float, default=0.0, nullable=False)
    max_uses = Column(Integer, nullable=True)  # None = unlimited
    times_used = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    valid_from = Column(DateTime, default=datetime.utcnow, nullable=False)
    valid_until = Column(DateTime, nullable=True)  # None = never expires
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def is_valid(self, order_subtotal: float) -> tuple[bool, str]:
        now = datetime.utcnow()
        if not self.is_active:
            return False, "Coupon is currently deactivated"
        if self.valid_from and now < self.valid_from:
            return False, "Coupon is not yet active"
        if self.valid_until and now > self.valid_until:
            return False, "Coupon has expired"
        if self.max_uses is not None and self.times_used >= self.max_uses:
            return False, "Coupon usage limit has been reached"
        if order_subtotal < self.min_order_amount:
            return False, f"Order subtotal must be at least ${self.min_order_amount:.2f} to use this coupon"
        return True, "Valid"

    def calculate_discount(self, order_subtotal: float) -> float:
        if self.discount_type == DiscountType.PERCENTAGE:
            discount = order_subtotal * (self.discount_value / 100.0)
        else:
            discount = self.discount_value
        return round(min(order_subtotal, max(0.0, discount)), 2)

    def __repr__(self) -> str:
        return f"<Coupon code={self.code} type={self.discount_type} val={self.discount_value}>"
