from unittest.mock import MagicMock
import pytest
from sqlalchemy.orm import Session
from app.models.product import Product
from app.models.user import User
from app.schemas.order import OrderCreate, OrderItemCreate
from app.services.order_service import create_order
from app.core.exceptions import InsufficientStockException


def test_postgresql_dialect_triggers_with_for_update_pessimistic_lock(
    db: Session,
    normal_user: User,
    sample_product: Product,
):
    """
    Verifies that when running on a PostgreSQL engine dialect,
    the inventory reservation logic explicitly triggers `with_for_update()`
    on the SQLAlchemy Query to establish a pessimistic row lock (SELECT ... FOR UPDATE).
    """
    sample_product.stock = 10
    db.commit()

    # Create mock session simulating a PostgreSQL dialect bind
    mock_db = MagicMock(spec=Session)
    mock_bind = MagicMock()
    mock_bind.dialect.name = "postgresql"
    mock_db.bind = mock_bind

    # Configure query chain
    mock_query = MagicMock()
    mock_db.query.return_value = mock_query
    mock_query.filter.return_value = mock_query

    # Mock product query returns
    mock_query.all.return_value = [sample_product]
    mock_query.first.return_value = sample_product
    mock_query.with_for_update.return_value = mock_query
    mock_query.populate_existing.return_value = mock_query

    order_in = OrderCreate(
        shipping_address="Calle 100 # 19-61, Bogotá, Colombia",
        items=[OrderItemCreate(product_id=sample_product.id, quantity=2)],
    )

    order = create_order(
        db=mock_db,
        user=normal_user,
        order_in=order_in,
    )

    # Verify with_for_update() was called
    mock_query.with_for_update.assert_called_once()
    # Verify stock decremented
    assert sample_product.stock == 8
    # Verify transaction commit was triggered
    mock_db.commit.assert_called_once()


def test_postgresql_insufficient_stock_raises_exception_and_does_not_commit(
    db: Session,
    normal_user: User,
    sample_product: Product,
):
    """
    Verifies that on PostgreSQL, if requested quantity exceeds locked row stock,
    InsufficientStockException is raised immediately without committing the transaction.
    """
    sample_product.stock = 1
    db.commit()

    mock_db = MagicMock(spec=Session)
    mock_bind = MagicMock()
    mock_bind.dialect.name = "postgresql"
    mock_db.bind = mock_bind

    mock_query = MagicMock()
    mock_db.query.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.all.return_value = [sample_product]
    mock_query.with_for_update.return_value = mock_query
    mock_query.populate_existing.return_value = mock_query
    mock_query.first.return_value = sample_product

    order_in = OrderCreate(
        shipping_address="Av. Chile # 7-45, Bogotá, Colombia",
        items=[OrderItemCreate(product_id=sample_product.id, quantity=5)],
    )

    with pytest.raises(InsufficientStockException):
        create_order(
            db=mock_db,
            user=normal_user,
            order_in=order_in,
        )

    # Commit must NEVER be called on insufficient stock
    mock_db.commit.assert_not_called()
