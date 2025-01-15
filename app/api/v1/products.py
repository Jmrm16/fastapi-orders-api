from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.product import Product
from app.schemas.product import ProductCreate, ProductUpdate, ProductResponse
from app.core.security import get_current_admin_user

router = APIRouter(prefix="/products", tags=["Products"])


@router.get("/", response_model=List[ProductResponse])
def list_products(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None, description="Search product by name or SKU"),
    in_stock_only: bool = Query(False, description="Filter products with stock > 0"),
    db: Session = Depends(get_db),
):
    """Retrieves a paginated list of active products with optional filters."""
    query = db.query(Product).filter(Product.is_active == True)

    if search:
        search_pattern = f"%{search.strip()}%"
        query = query.filter((Product.name.ilike(search_pattern)) | (Product.sku.ilike(search_pattern)))

    if in_stock_only:
        query = query.filter(Product.stock > 0)

    products = query.offset(skip).limit(limit).all()
    return products


@router.get("/{product_id}", response_model=ProductResponse)
def get_product(product_id: int, db: Session = Depends(get_db)):
    """Fetches details for a single product by ID."""
    product = db.query(Product).filter(Product.id == product_id, Product.is_active == True).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID {product_id} was not found."
        )
    return product


@router.post("/", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
def create_product(
    product_in: ProductCreate,
    db: Session = Depends(get_db),
    _admin = Depends(get_current_admin_user),
):
    """Creates a new product catalog item (Administrator only)."""
    existing_sku = db.query(Product).filter(Product.sku == product_in.sku).first()
    if existing_sku:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"A product with SKU '{product_in.sku}' already exists."
        )

    product = Product(**product_in.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@router.patch("/{product_id}", response_model=ProductResponse)
def update_product(
    product_id: int,
    product_in: ProductUpdate,
    db: Session = Depends(get_db),
    _admin = Depends(get_current_admin_user),
):
    """Partially updates product inventory or pricing (Administrator only)."""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID {product_id} not found."
        )

    update_data = product_in.model_dump(exclude_unset=True)
    for field, val in update_data.items():
        setattr(product, field, val)

    db.commit()
    db.refresh(product)
    return product
