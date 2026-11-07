import os
import pytest
from concurrent.futures import ThreadPoolExecutor, as_completed
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session

from app.main import app
from app.database import Base, get_db
from app.models.user import User
from app.models.product import Product
from app.services.auth_service import get_password_hash, create_access_token


def test_inventory_depletion_boundary_and_rejection(
    client: TestClient,
    db: Session,
    normal_user_token_headers: dict,
    sample_product: Product,
):
    """
    Inventory Boundary & Zero-Overselling Guard:
    Verifies that when a product's stock is depleted to zero, any subsequent
    order request is strictly rejected with HTTP 400 (Insufficient Stock).
    Stock must never fall into negative numbers.
    """
    initial_stock = 4
    sample_product.stock = initial_stock
    db.commit()
    db.refresh(sample_product)

    order_payload = {
        "shipping_address": "Av. El Dorado # 69-76, Bogotá, Colombia",
        "items": [{"product_id": sample_product.id, "quantity": 1}],
    }

    # 1. Place orders one by one to consume all available stock
    for i in range(initial_stock):
        resp = client.post(
            "/api/v1/orders/",
            json=order_payload,
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 201
        db.refresh(sample_product)
        assert sample_product.stock == initial_stock - (i + 1)

    # 2. At this point, stock must be exactly 0
    assert sample_product.stock == 0

    # 3. Next attempt MUST fail with 400 Bad Request
    fail_resp = client.post(
        "/api/v1/orders/",
        json=order_payload,
        headers=normal_user_token_headers,
    )
    assert fail_resp.status_code == 400
    err_body = fail_resp.json()
    assert "Insufficient" in err_body["detail"] or "stock" in err_body["detail"].lower()

    # 4. Stock remains strictly 0
    db.refresh(sample_product)
    assert sample_product.stock == 0


def test_bulk_order_exceeding_total_inventory_fails_atomically(
    client: TestClient,
    db: Session,
    normal_user_token_headers: dict,
    sample_product: Product,
):
    """
    Atomicity Test:
    Attempting to order quantity > available stock fails immediately without
    modifying any inventory.
    """
    initial_stock = sample_product.stock
    resp = client.post(
        "/api/v1/orders/",
        json={
            "shipping_address": "Carrera 7 # 32-16, Medellín, Colombia",
            "items": [{"product_id": sample_product.id, "quantity": initial_stock + 10}],
        },
        headers=normal_user_token_headers,
    )
    assert resp.status_code == 400
    db.refresh(sample_product)
    assert sample_product.stock == initial_stock


def test_concurrent_connections_race_condition_prevents_overselling():
    """
    Multi-threaded Concurrency Stress Test:
    Spins up 8 parallel worker threads attempting to purchase the last 3 remaining units
    of an inventory item simultaneously.
    Verifies that the atomic database UPDATE (WHERE stock >= qty) strictly prevents overselling:
    - Exactly 3 requests succeed (HTTP 201).
    - Exactly 5 requests are gracefully rejected (HTTP 400 Insufficient Stock).
    - Final inventory stock is strictly 0 and never goes negative.
    """
    db_file = os.path.abspath("test_concurrency_stress.sqlite3")
    if os.path.exists(db_file):
        try:
            os.remove(db_file)
        except OSError:
            pass

    test_engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False, "timeout": 30.0},
    )

    @event.listens_for(test_engine, "connect")
    def configure_wal_mode(conn, record):
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.close()

    Base.metadata.create_all(bind=test_engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    try:
        # Seed test data
        seed_session = TestingSession()
        test_user = User(
            email="stress_tester@commerce.io",
            full_name="Stress Tester",
            hashed_password=get_password_hash("Password123!"),
            is_active=True,
            is_admin=False,
        )
        available_units = 3
        test_product = Product(
            sku="CONCURRENT-GPU-RTX",
            name="Nvidia GeForce RTX 4090",
            price=1599.99,
            stock=available_units,
            is_active=True,
        )
        seed_session.add_all([test_user, test_product])
        seed_session.commit()
        user_id = test_user.id
        product_id = test_product.id
        seed_session.close()

        auth_token = create_access_token(subject=user_id)
        auth_headers = {"Authorization": f"Bearer {auth_token}"}

        def override_concurrent_db():
            session = TestingSession()
            try:
                yield session
            finally:
                session.close()

        app.dependency_overrides[get_db] = override_concurrent_db

        total_threads = 8
        order_payload = {
            "shipping_address": "Carrera 15 # 85-30, Bogotá, Colombia",
            "items": [{"product_id": product_id, "quantity": 1}],
        }

        def fire_order(thread_id: int):
            client = TestClient(app)
            return client.post(
                "/api/v1/orders/",
                json=order_payload,
                headers={**auth_headers, "X-Thread-ID": str(thread_id)},
            )

        with ThreadPoolExecutor(max_workers=total_threads) as executor:
            futures = [executor.submit(fire_order, i) for i in range(total_threads)]
            responses = [f.result() for f in as_completed(futures)]

        status_codes = [r.status_code for r in responses]
        successful = [code for code in status_codes if code == 201]
        rejected = [code for code in status_codes if code == 400]

        assert len(successful) == available_units, (
            f"Expected exactly {available_units} successful orders, got {len(successful)}. Codes: {status_codes}"
        )
        assert len(rejected) == (total_threads - available_units), (
            f"Expected {total_threads - available_units} rejections, got {len(rejected)}. Codes: {status_codes}"
        )

        # Confirm zero inventory in database
        verify_session = TestingSession()
        final_product = verify_session.query(Product).filter_by(id=product_id).first()
        assert final_product.stock == 0, f"Stock should be 0, but was {final_product.stock}"
        verify_session.close()

    finally:
        app.dependency_overrides.clear()
        test_engine.dispose()
        for ext in ["", "-wal", "-shm"]:
            path = db_file + ext
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
