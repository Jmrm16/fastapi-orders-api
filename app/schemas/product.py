from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class ProductBase(BaseModel):
    sku: str = Field(..., max_length=64, description="Unique stock keeping unit")
    name: str = Field(..., min_length=2, max_length=255)
    description: Optional[str] = None
    price: float = Field(..., gt=0, description="Price must be strictly positive")
    stock: int = Field(default=0, ge=0, description="Available inventory quantity")
    is_active: bool = True


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=255)
    description: Optional[str] = None
    price: Optional[float] = Field(None, gt=0)
    stock: Optional[int] = Field(None, ge=0)
    is_active: Optional[bool] = None


class ProductResponse(ProductBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
