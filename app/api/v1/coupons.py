from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.coupon import Coupon
from app.models.user import User
from app.schemas.coupon import CouponCreate, CouponResponse, CouponValidateResponse
from app.core.security import get_current_admin_user, get_current_user

router = APIRouter(prefix="/coupons", tags=["Coupons"])


@router.post("/", response_model=CouponResponse, status_code=status.HTTP_201_CREATED)
def create_coupon(
    coupon_in: CouponCreate,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin_user),
):
    """Admin endpoint to create a new promotional coupon code."""
    normalized_code = coupon_in.code.strip().upper()
    existing = db.query(Coupon).filter(Coupon.code == normalized_code).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Coupon code '{normalized_code}' already exists",
        )

    coupon = Coupon(
        code=normalized_code,
        discount_type=coupon_in.discount_type,
        discount_value=coupon_in.discount_value,
        min_order_amount=coupon_in.min_order_amount,
        max_uses=coupon_in.max_uses,
        valid_until=coupon_in.valid_until,
        is_active=coupon_in.is_active,
    )
    db.add(coupon)
    db.commit()
    db.refresh(coupon)
    return coupon


@router.get("/", response_model=List[CouponResponse])
def list_coupons(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin_user),
):
    """Admin endpoint to list all available promo codes."""
    return db.query(Coupon).offset(skip).limit(limit).all()


@router.get("/validate/{code}", response_model=CouponValidateResponse)
def validate_coupon(
    code: str,
    subtotal: float = Query(0.0, ge=0.0, description="Order subtotal to evaluate discount for"),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """
    Customer endpoint to preview coupon validity and estimated discount
    prior to submitting checkout.
    """
    normalized_code = code.strip().upper()
    coupon = db.query(Coupon).filter(Coupon.code == normalized_code).first()
    if not coupon:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Coupon code '{normalized_code}' not found",
        )

    is_valid, reason = coupon.is_valid(subtotal)
    discount = coupon.calculate_discount(subtotal) if is_valid else 0.0

    return CouponValidateResponse(
        code=coupon.code,
        is_valid=is_valid,
        discount_type=coupon.discount_type,
        discount_value=coupon.discount_value,
        estimated_discount=discount,
        message=reason,
    )


@router.delete("/{coupon_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_coupon(
    coupon_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin_user),
):
    """Admin endpoint to deactivate a promo code."""
    coupon = db.query(Coupon).filter(Coupon.id == coupon_id).first()
    if not coupon:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Coupon with ID {coupon_id} not found",
        )
    coupon.is_active = False
    db.commit()
    return None
