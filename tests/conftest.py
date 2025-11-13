import pytest
from typing import Generator
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.user import User
from app.models.product import Product
from app.services.auth_service import get_password_hash, create_access_token

# In-memory SQLite with StaticPool so all threads/sessions share the same in-memory database
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db() -> Generator[Session, None, None]:
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db: Session) -> Generator[TestClient, None, None]:
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def admin_user(db: Session) -> User:
    user = User(
        email="admin@novacommerce.io",
        full_name="Admin User",
        hashed_password=get_password_hash("AdminPass123!"),
        is_active=True,
        is_admin=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def admin_token_headers(admin_user: User) -> dict:
    token = create_access_token(subject=admin_user.id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def normal_user(db: Session) -> User:
    user = User(
        email="dev.candidate@example.com",
        full_name="Candidate Dev",
        hashed_password=get_password_hash("SecretPassword123!"),
        is_active=True,
        is_admin=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def normal_user_token_headers(normal_user: User) -> dict:
    token = create_access_token(subject=normal_user.id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def sample_product(db: Session) -> Product:
    product = Product(
        sku="DEV-KEYBOARD-RGB",
        name="Mechanical Wireless Keyboard",
        description="Low latency mechanical keyboard with hot-swappable switches",
        price=89.99,
        stock=15,
        is_active=True,
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return product
