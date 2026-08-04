# FastAPI Orders API

Production-oriented asynchronous e-commerce order management and atomic inventory reservation service built with **Python 3.11+**, **FastAPI**, **SQLAlchemy**, and **Pydantic v2**.

The service is designed to demonstrate real-world backend engineering patterns: ACID-compliant inventory reservation, finite state machine order lifecycles, domain exception hierarchies, role-based access control (RBAC), and deterministic database session management.

---

## Table of Contents

- [Goals & Design Principles](#goals--design-principles)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Architecture & Core Concepts](#architecture--core-concepts)
  - [1. Atomic Inventory Reservation](#1-atomic-inventory-reservation)
  - [2. Order Lifecycle Finite State Machine](#2-order-lifecycle-finite-state-machine)
  - [3. Domain Exception Hierarchy](#3-domain-exception-hierarchy)
  - [4. Authentication & Role-Based Access Control (RBAC)](#4-authentication--role-based-access-control-rbac)
  - [5. Payment Gateway Webhook Ingestion](#5-payment-gateway-webhook-ingestion)
- [Current Implementation & Endpoints](#current-implementation--endpoints)
  - [Authentication Router (`/api/v1/auth`)](#authentication-router-apiv1auth)
  - [Product Catalog Router (`/api/v1/products`)](#product-catalog-router-apiv1products)
  - [Order Fulfillment Router (`/api/v1/orders`)](#order-fulfillment-router-apiv1orders)
  - [Payment Webhook Router (`/api/v1/webhooks`)](#payment-webhook-router-apiv1webhooks)
- [Database Strategy](#database-strategy)
- [Testing Architecture & Pytest Fixtures](#testing-architecture--pytest-fixtures)
- [Local Development & Quickstart](#local-development--quickstart)
  - [Option A: Local Virtual Environment (Zero-config SQLite)](#option-a-local-virtual-environment-zero-config-sqlite)
  - [Option B: Docker Compose (PostgreSQL Production Mirror)](#option-b-docker-compose-postgresql-production-mirror)
- [Continuous Integration (CI)](#continuous-integration-ci)
- [License](#license)

---

## Goals & Design Principles

The primary objectives of this repository are to demonstrate production-grade software engineering practices:

- **Domain-Driven Design (DDD):** Separation of presentation (FastAPI routers), domain schemas (Pydantic v2), database entities (SQLAlchemy ORM), and business logic (Service Layer).
- **Concurrency & Race Condition Prevention:** Atomic inventory deduction executed within single database transactions to eliminate overselling under high concurrency.
- **Finite State Machine (FSM):** Strict validation of order status progressions, rejecting invalid business transitions (e.g., preventing cancellation of dispatched orders).
- **Decoupled Architecture:** Business rules live in `app/services/` rather than embedded inside API route handlers.
- **Fail-Fast & Predictable Error Translation:** Internal business exceptions (`InsufficientStockException`, `OrderStateTransitionException`) map cleanly to HTTP status codes with structured JSON error bodies.
- **Deterministic Resource Cleanup:** Database session lifecycle managed via FastAPI dependency injection and context managers.
- **Test Isolation:** 100% in-memory database test execution using SQLite `StaticPool` and dependency overrides, completing full test suites in under 4 seconds without external database dependencies.

---

## Tech Stack

| Technology | Role in Project |
| :--- | :--- |
| **Python 3.11+** | Runtime environment leveraging modern type annotations and union syntax. |
| **FastAPI** | High-performance asynchronous web framework, dependency injection system, and automatic OpenAPI generation. |
| **SQLAlchemy 2.0** | ORM and SQL toolkit for declarative data modeling and transactional persistence. |
| **Pydantic v2** | Request validation, serialization, and schema contracts (`ConfigDict(from_attributes=True)`). |
| **pydantic-settings** | Strict, environment-driven configuration management with `.env` file support. |
| **bcrypt** | Direct cryptographic salted password hashing. |
| **python-jose** | Signed JWT access token issuance and signature verification. |
| **pytest** | Automated test suite execution, fixtures, and assertion frameworks. |
| **HTTPX / TestClient** | Synchronous ASGI in-memory request dispatching for integration testing. |
| **Docker & Docker Compose** | Containerized deployment and multi-service orchestration with PostgreSQL. |
| **GitHub Actions** | Automated CI pipeline running linting and test suites on every pull request. |

---

## Project Structure

```text
fastapi-orders-api/
├── .github/
│   └── workflows/
│       └── ci.yml               # Automated CI pipeline for pull requests and pushes
├── app/
│   ├── api/
│   │   ├── __init__.py
│   │   └── v1/
│   │       ├── __init__.py      # v1 Router aggregator
│   │       ├── auth.py          # /auth (register, login, me)
│   │       ├── products.py      # /products (search, pagination, admin CRUD)
│   │       ├── orders.py        # /orders (placement, history, cancel, status)
│   │       └── webhooks.py      # /webhooks (asynchronous payment processor events)
│   ├── core/
│   │   ├── __init__.py
│   │   ├── security.py          # OAuth2PasswordBearer & RBAC dependency guards
│   │   └── exceptions.py        # Custom domain exceptions (CommerceException)
│   ├── models/                  # SQLAlchemy ORM declarative entities
│   │   ├── __init__.py
│   │   ├── user.py              # User entity with hashed credentials and roles
│   │   ├── product.py           # Product catalog entity with stock levels
│   │   └── order.py             # Order and OrderItem entities with OrderStatus enum
│   ├── schemas/                 # Pydantic v2 data transfer objects (DTOs)
│   │   ├── __init__.py
│   │   ├── user.py              # Registration, login, and user profile schemas
│   │   ├── product.py           # Catalog filter, creation, and response schemas
│   │   └── order.py             # Order placement, item nested schemas, status update
│   ├── services/                # Encapsulated domain business logic
│   │   ├── __init__.py
│   │   ├── auth_service.py      # Bcrypt hashing and JWT encoding/decoding
│   │   └── order_service.py     # Atomic checkout and state machine orchestration
│   ├── config.py                # Pydantic-settings global environment configuration
│   ├── database.py              # Engine setup, session pooling, and get_db dependency
│   └── main.py                  # Application factory, lifespan, CORS, and exception handlers
├── tests/
│   ├── __init__.py
│   ├── conftest.py              # Pytest in-memory database fixtures & auth headers
│   ├── test_auth.py             # Authentication & token verification tests
│   ├── test_products.py         # Catalog search, pagination, and RBAC tests
│   └── test_orders.py           # Atomic inventory deduction, FSM, and webhook tests
├── scripts/
│   └── seed_data.py             # Development database seeder with sample catalog
├── .env.example                 # Template for local environment variables
├── .gitignore                   # Git exclusion rules for compiled artifacts & virtualenvs
├── Dockerfile                   # Multi-stage production container build
├── docker-compose.yml           # Local production-mirror (FastAPI + PostgreSQL 15)
├── pytest.ini                   # Pytest configuration and pythonpath discovery
└── requirements.txt             # Pinned production and test dependencies
```

---

## Architecture & Core Concepts

### 1. Atomic Inventory Reservation

In high-concurrency e-commerce environments, standard read-then-write updates lead to overselling (*race conditions*). `FastAPI Orders API` encapsulates inventory reservation inside a single transactional block in `app/services/order_service.py`:

```python
# 1. Fetch and validate all requested items in a single query
products = db.query(Product).filter(Product.id.in_(requested_product_ids)).all()

# 2. Verify stock sufficiency for every line item
for item in order_in.items:
    product = products_by_id[item.product_id]
    if product.stock < item.quantity:
        raise InsufficientStockException(product.name, product.stock, item.quantity)

# 3. Atomically decrement inventory and persist Order + OrderItems
for item in order_in.items:
    product.stock -= item.quantity
    db.add(OrderItem(...))

db.commit()
```

If any single item in the order has insufficient stock, an `InsufficientStockException` is raised, rolling back the entire transaction before any stock is deducted.

### 2. Order Lifecycle Finite State Machine

Orders must obey strict operational transitions. The business rules enforce legal transitions and protect terminal states:

```text
               ┌─────────────┐
               │   PENDING   │
               └──────┬──────┘
                      │
           ┌──────────┴──────────┐
           ▼                     ▼
     ┌───────────┐         ┌───────────┐
     │   PAID    │         │ CANCELLED │ ◄── [Stock Restocked Automatically]
     └─────┬─────┘         └───────────┘
           │                     ▲
           ▼                     │
     ┌───────────┐               │
     │PROCESSING ├───────────────┘
     └─────┬─────┘
           │
           ▼
     ┌───────────┐
     │  SHIPPED  │ (Terminal State - Cannot be cancelled)
     └───────────┘
```

- **Stock Reversion:** When an order is cancelled from `PENDING`, `PAID`, or `PROCESSING`, the service automatically re-credits the reserved quantities back to the `products.stock` inventory.
- **Immutability:** Once an order reaches `SHIPPED` or `CANCELLED`, any transition attempt raises an `OrderStateTransitionException` returning HTTP 400.

### 3. Domain Exception Hierarchy

Rather than scattering `HTTPException` throughout service layers, domain modules raise domain-specific exceptions inheriting from `CommerceException`:

```python
class CommerceException(Exception):
    """Base domain exception."""

class InsufficientStockException(CommerceException):
    """Raised when available stock cannot satisfy requested quantity."""

class OrderStateTransitionException(CommerceException):
    """Raised when an illegal order status change is attempted."""

class EntityNotFoundException(CommerceException):
    """Raised when an entity ID is missing."""
```

The global FastAPI exception handler in `app/main.py` catches `CommerceException` and translates it into a structured, client-friendly JSON response:

```json
{
  "error": "InsufficientStockException",
  "message": "Insufficient stock for 'Mechanical Wireless Keyboard'. Available: 2, Requested: 5."
}
```

### 4. Authentication & Role-Based Access Control (RBAC)

- **Password Hashing:** Directly uses the industry-standard `bcrypt` library with cryptographic salt generation, avoiding deprecated wrapper layers.
- **Stateless Tokens:** Signs and validates HMAC-SHA256 (`HS256`) JSON Web Tokens containing user subject and expiration claims.
- **Dependency Inversion Guards:**
  - `get_current_user`: Decodes Bearer token and verifies user existence.
  - `get_current_active_user`: Enforces that the account is not deactivated.
  - `get_current_admin_user`: Enforces `is_admin == True`, preventing non-admin users from creating products, altering stock levels, or forcing manual order state transitions.

### 5. Payment Gateway Webhook Ingestion

The webhook endpoint (`/api/v1/webhooks/payment`) simulates event notifications from payment providers (Stripe, PayPal, MercadoPago):
- Listens for `payment.succeeded` events to transition orders from `PENDING` to `PAID`.
- Listens for `payment.failed` events to cancel the order and release inventory.
- Handles duplicate/idempotent callbacks gracefully without throwing errors.

---

## Current Implementation & Endpoints

### Authentication Router (`/api/v1/auth`)

#### `POST /api/v1/auth/register`
Creates a customer account. Validates email uniqueness and enforces minimum password length.

```bash
curl -X POST "http://localhost:8000/api/v1/auth/register" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "developer@company.com",
    "password": "SecurePassword123!",
    "full_name": "Senior Candidate"
  }'
```

#### `POST /api/v1/auth/login`
Authenticates user credentials using OAuth2 password flow and returns a Bearer JWT token.

```bash
curl -X POST "http://localhost:8000/api/v1/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=developer@company.com&password=SecurePassword123!"
```

*Response:*
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "user": {
    "email": "developer@company.com",
    "full_name": "Senior Candidate",
    "is_active": true,
    "id": 1,
    "is_admin": false,
    "created_at": "2026-10-16T23:25:00"
  }
}
```

#### `GET /api/v1/auth/me`
Retrieves authenticated user profile based on Bearer token.

---

### Product Catalog Router (`/api/v1/products`)

#### `GET /api/v1/products/`
Retrieves products with query filtering and pagination.

- `skip` (int, default: 0): Offset for pagination.
- `limit` (int, default: 20, max: 100): Page size.
- `search` (str, optional): Case-insensitive match on product name or SKU.
- `in_stock_only` (bool, default: false): Filters out items with `stock == 0`.

```bash
curl "http://localhost:8000/api/v1/products/?search=Keyboard&in_stock_only=true"
```

#### `POST /api/v1/products/` *(Admin Only)*
Creates a product listing. Requires admin token.

#### `PATCH /api/v1/products/{id}` *(Admin Only)*
Partially updates inventory or pricing.

---

### Order Fulfillment Router (`/api/v1/orders`)

#### `POST /api/v1/orders/`
Places a new order, calculates subtotals, and atomically deducts stock.

```bash
curl -X POST "http://localhost:8000/api/v1/orders/" \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "shipping_address": "456 Enterprise Way, Austin, TX",
    "items": [
      {"product_id": 1, "quantity": 2}
    ]
  }'
```

#### `GET /api/v1/orders/`
Returns order history for the authenticated user (or all system orders if admin).

#### `POST /api/v1/orders/{id}/cancel`
Cancels an order and automatically restores stock back to product inventory.

---

### Payment Webhook Router (`/api/v1/webhooks`)

#### `POST /api/v1/webhooks/payment`
Receives payment gateway notifications and synchronizes order status.

```bash
curl -X POST "http://localhost:8000/api/v1/webhooks/payment" \
  -H "Content-Type: application/json" \
  -d '{
    "event": "payment.succeeded",
    "order_id": 1,
    "payment_reference": "ch_3NabcXYZ123",
    "status": "succeeded"
  }'
```

---

## Database Strategy

The application is architected to switch seamlessly between development and production storage via the `DATABASE_URL` environment variable:

- **Local Development:** Defaults to SQLite (`sqlite:///./nova_commerce.db`) with `connect_args={"check_same_thread": False}`. No external daemon required.
- **Testing:** Uses in-memory SQLite (`sqlite:///:memory:`) paired with `StaticPool` to guarantee complete state isolation and ultra-fast test execution.
- **Production / Docker:** Connects to PostgreSQL (`postgresql+psycopg2://user:password@host:5432/dbname`) using connection pooling (`pool_pre_ping=True`).

---

## Testing Architecture & Pytest Fixtures

The test suite in `tests/` contains comprehensive unit and integration tests covering positive paths, business validation rejections, and security barriers.

### Test Isolation with `StaticPool`
In SQLite, in-memory databases (`:memory:`) discard their data when a connection is closed. By configuring `StaticPool` in `tests/conftest.py`, all application threads and database sessions during a test function share the exact same in-memory instance:

```python
engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
```

### Running the Test Suite

```bash
pytest -v
```

*Output:*
```text
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-9.1.1, pluggy-1.7.0
rootdir: C:\xampp\htdocs\fastapi-orders-api
configfile: pytest.ini
collected 15 items

tests/test_auth.py::test_register_user_success PASSED                    [  6%]
tests/test_auth.py::test_register_duplicate_email_fails PASSED           [ 13%]
tests/test_auth.py::test_login_success PASSED                            [ 20%]
tests/test_auth.py::test_login_wrong_password_fails PASSED               [ 26%]
tests/test_auth.py::test_read_me_profile PASSED                          [ 33%]
tests/test_orders.py::test_place_order_success_deducts_inventory PASSED  [ 40%]
tests/test_orders.py::test_place_order_insufficient_stock_fails PASSED   [ 46%]
tests/test_orders.py::test_cancel_order_restores_inventory PASSED        [ 53%]
tests/test_orders.py::test_illegal_status_transition_fails PASSED        [ 60%]
tests/test_orders.py::test_payment_webhook_marks_order_paid PASSED       [ 66%]
tests/test_products.py::test_list_products_empty PASSED                  [ 73%]
tests/test_products.py::test_list_products_with_items PASSED             [ 80%]
tests/test_products.py::test_search_product_by_query PASSED              [ 86%]
tests/test_products.py::test_create_product_admin_only PASSED            [ 93%]
tests/test_products.py::test_update_product_stock_admin PASSED           [100%]

======================== 15 passed, 1 warning in 3.42s ========================
```

---

## Local Development & Quickstart

### Option A: Local Virtual Environment (Zero-config SQLite)

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Jmrm16/fastapi-orders-api.git
   cd fastapi-orders-api
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python -m venv .venv

   # Windows (PowerShell)
   .\.venv\Scripts\Activate.ps1

   # Linux / macOS
   source .venv/bin/activate
   ```

3. **Install pinned dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Populate demo data (admin, customer, sample products):**
   ```bash
   python scripts/seed_data.py
   ```
   > **Seed Credentials:**
   > - **Admin:** `admin@novacommerce.io` / `AdminPass123!`
   > - **Customer:** `customer@novacommerce.io` / `CustomerPass123!`

5. **Start the development server with live reload:**
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```

6. Open your browser and navigate to:
   - **Interactive OpenAPI Documentation:** [http://localhost:8000/docs](http://localhost:8000/docs)
   - **Alternative ReDoc UI:** [http://localhost:8000/redoc](http://localhost:8000/redoc)
   - **Health Check:** [http://localhost:8000/health](http://localhost:8000/health)

---

### Option B: Docker Compose (PostgreSQL Production Mirror)

To run the complete production topology including PostgreSQL 15:

```bash
docker compose up --build
```

The API will be accessible on port `8000` with the PostgreSQL database persisting data to a named Docker volume (`postgres_data`).

---

## Continuous Integration (CI)

Every commit and pull request triggers the automated test pipeline defined in `.github/workflows/ci.yml`:

```yaml
name: CI Test Suite

on:
  push:
    branches: [ main, master, develop ]
  pull_request:
    branches: [ main, master ]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v3
    - name: Set up Python 3.11
      uses: actions/setup-python@v4
      with:
        python-version: "3.11"
        cache: 'pip'
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -r requirements.txt
    - name: Run Pytest test suite
      run: pytest -v --tb=short
```

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.













