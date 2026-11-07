import os
import pytest
from concurrent.futures import ThreadPoolExecutor, as_completed
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.main import app
from app.database import Base, get_db
from app.models.user import User
from app.models.product import Product
from app.services.auth_service import get_password_hash, create_access_token


def is_postgres_available() -> bool:
    url = os.getenv("DATABASE_URL", "")
    return url.startswith("postgresql")


@pytest.mark.skipif(
    not is_postgres_available(),
    reason="PostgreSQL not configured in current environment. This test executes against real Postgres in GitHub Actions CI.",
)
def test_postgres_concurrent_with_for_update_row_locking_e2e():
    """
    End-to-End Multi-threaded Concurrency Test on REAL PostgreSQL:
    Spins up 8 parallel worker threads executing simultaneous checkout requests
    against PostgreSQL 16 with pessimistic row locking (`SELECT ... FOR UPDATE` via `with_for_update()`).

    Verifies:
    - Exactly 3 orders succeed (HTTP 201).
    - Exactly 5 orders are rejected with HTTP 400 Insufficient Stock.
    - Zero overselling occurs. Final stock is strictly 0.
    """
    pg_url = os.getenv("DATABASE_URL")
    test_engine = create_engine(
        pg_url,
        pool_size=15,
        max_overflow=10,
        pool_pre_ping=True,
    )
    Base.metadata.create_all(bind=test_engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    try:
        session = TestingSession()
        test_user = User(
            email="pg_stress_tester@commerce.io",
            full_name="PG Stress Tester",
            hashed_password=get_password_hash("SecretPassword123!"),
            is_active=True,
            is_admin=False,
        )
        available_units = 3
        test_product = Product(
            sku="PG-LOCK-RTX-5090",
            name="PG Locked Graphics Card",
            price=2499.99,
            stock=available_units,
            is_active=True,
        )
        session.add_all([test_user, test_product])
        session.commit()
        user_id = test_user.id
        product_id = test_product.id
        session.close()

        auth_token = create_access_token(subject=user_id)
        auth_headers = {"Authorization": f"Bearer {auth_token}"}

        def override_db():
            db_sess = TestingSession()
            try:
                yield db_sess
            finally:
                db_sess.close()

        app.dependency_overrides[get_db] = override_db

        total_threads = 8
        order_payload = {
            "shipping_address": "Carrera 7 # 72-01, Bogotá, Colombia",
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
            f"Expected {available_units} successful orders on PostgreSQL with FOR UPDATE, got {len(successful)}. Codes: {status_codes}"
        )
        assert len(rejected) == (total_threads - available_units), (
            f"Expected {total_threads - available_units} rejections, got {len(rejected)}. Codes: {status_codes}"
        )

        verify_session = TestingSession()
        final_product = verify_session.query(Product).filter_by(id=product_id).first()
        assert final_product.stock == 0, f"PostgreSQL stock should be 0, but was {final_product.stock}"
        verify_session.close()

    finally:
        app.dependency_overrides.clear()
        test_engine.dispose()
