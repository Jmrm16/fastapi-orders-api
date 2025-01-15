from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, Text, Boolean, DateTime
from sqlalchemy.orm import relationship
from app.database import Base


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    sku = Column(String(64), unique=True, index=True, nullable=False)
    name = Column(String(255), index=True, nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Float, nullable=False)
    stock = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    order_items = relationship("OrderItem", back_populates="product")

    def __repr__(self) -> str:
        return f"<Product id={self.id} sku={self.sku} name={self.name}>"
