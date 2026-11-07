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
| **SQLAlchemy 2.0** | ORM and SQL toolkit with dialect-aware pessimistic row locking (`with_for_update()`). |
| **PostgreSQL 16** | Production relational database engine configured with connection pooling (`pool_size=20`, `max_overflow=10`). |
| **Redis 7** | High-throughput asynchronous task queue with automated retries and Dead Letter Queue (DLQ). |
| **Pydantic v2** | Request validation, serialization, and schema contracts (`ConfigDict(from_attributes=True)`). |
| **pydantic-settings** | Strict, environment-driven configuration management with `.env` file support. |
| **bcrypt** | Direct cryptographic salted password hashing. |
| **python-jose** | Signed JWT access token issuance and signature verification. |
| **pytest** | Automated test suite execution (37 tests, 83% coverage), fixtures, and assertion frameworks. |
| **HTTPX / TestClient** | Synchronous ASGI in-memory request dispatching for integration testing. |
| **Docker & Docker Compose** | Containerized multi-service orchestration (FastAPI API + Background Worker + PostgreSQL 16 + Redis 7). |
| **GitHub Actions** | Automated CI pipeline running linting and test suites on every pull request. |

---

## Project Structure

```text
fastapi-orders-api/
├── .github/workflows/ci.yml     # Automated CI pipeline (linting & pytest)
├── alembic/                     # Database migrations & revision history
│   ├── env.py                   # Migration environment linking SQLAlchemy Base metadata
│   └── versions/                # Versioned migration revision scripts
├── app/
│   ├── api/v1/
│   │   ├── __init__.py          # v1 Router aggregator
│   │   ├── auth.py              # /auth (register, login, me)
│   │   ├── coupons.py           # /coupons (promo code admin CRUD & customer validation)
│   │   ├── orders.py            # /orders (checkout, idempotency, audit trail, DLQ management)
│   │   ├── products.py          # /products (search, pagination, admin inventory)
│   │   └── webhooks.py          # /webhooks (payment processor events)
│   ├── core/
│   │   ├── exceptions.py        # Domain exceptions (CommerceException hierarchy)
│   │   └── security.py          # OAuth2PasswordBearer, Bcrypt & RBAC guards
│   ├── models/                  # SQLAlchemy ORM declarative models
│   │   ├── coupon.py            # Coupon (percentage & fixed promo codes with limits)
│   │   ├── order.py             # Order, OrderItem, OrderEvent (audit trail)
│   │   ├── product.py           # Product catalog entity with stock levels
│   │   └── user.py              # User entity with hashed credentials and roles
│   ├── schemas/                 # Pydantic v2 DTOs (validation & serialization)
│   │   ├── coupon.py            # Coupon validation, creation, and calculation schemas
│   │   ├── order.py             # OrderCreate, OrderResponse, OrderEventResponse
│   │   ├── product.py           # ProductCreate, ProductResponse
│   │   └── user.py              # UserRegister, UserLogin, UserResponse
│   ├── services/
│   │   ├── auth_service.py      # JWT encoding/decoding & credential verification
│   │   ├── order_service.py     # Pessimistic checkout with with_for_update(), state machine & FSM
│   │   └── queue_service.py     # Redis task queues, retry backoff & Dead Letter Queue (DLQ)
│   ├── tasks/
│   │   ├── __init__.py          # Asynchronous worker module
│   │   └── worker.py            # Standalone daemon process listening on Redis task queues
│   ├── config.py                # Pydantic-settings environment variables (PostgreSQL & Redis URLs)
│   ├── database.py              # Dialect-aware pooling (PostgreSQL pool_size=20, SQLite WAL mode)
│   └── main.py                  # FastAPI factory, telemetry middleware & exception handlers
├── tests/
│   ├── conftest.py              # Shared fixtures, auth tokens & in-memory SQLite isolation
│   ├── test_analytics_and_idempotency.py # Idempotency-Key guard & SQL GMV aggregations
│   ├── test_auth.py             # Authentication, duplicate registration & JWT validation
│   ├── test_concurrency.py      # Multithreaded stress test & atomic stock deduction
│   ├── test_coupons_and_events.py # Promo engine, expiration, limits & audit history
│   ├── test_health.py           # Liveness & database connection pool readiness probes
│   ├── test_orders.py           # Checkout, inventory rollback on cancel & webhook sync
│   ├── test_products.py         # Catalog search, filtering & RBAC authorization
│   ├── test_queue_and_dlq.py    # Redis task processing, retry limits & DLQ recovery
│   └── test_row_locking.py      # PostgreSQL SELECT FOR UPDATE pessimistic locking verification
├── Makefile                     # Standard developer commands (test, test-cov, dev, migrate)
├── alembic.ini                  # Alembic CLI migration configuration
├── Dockerfile                   # Multi-stage production container build
├── docker-compose.yml           # Multi-service stack (API + Worker + Postgres 16 + Redis 7)
├── pytest.ini                   # Pytest testpaths and discovery configuration
└── requirements.txt             # Pinned production and testing dependencies
```

---

## Architecture & Core Concepts

### 1. Atomic Inventory Reservation & Pessimistic Row Locking

In high-concurrency e-commerce environments, standard read-then-write updates lead to overselling (*race conditions*). `FastAPI Orders API` leverages **dialect-aware inventory reservation** inside a single ACID transactional block in `app/services/order_service.py`:

- **PostgreSQL (Production):** Uses pessimistic row locking (`SELECT ... FOR UPDATE` via SQLAlchemy's `.with_for_update()`). Any concurrent checkout transaction for the same product SKU is blocked at the database engine level until the current transaction commits or rolls back, strictly guaranteeing zero overselling.
- **SQLite (Local & CI unit testing):** Uses atomic conditional database updates (`WHERE id = :id AND stock >= :qty`) with WAL mode.

```python
# PostgreSQL Pessimistic Row Locking:
for item in order_in.items:
    if db.bind and getattr(db.bind.dialect, "name", "") == "postgresql":
        # SELECT * FROM products WHERE id = :id FOR UPDATE
        locked_product = (
            db.query(Product)
            .filter(Product.id == item.product_id)
            .with_for_update()
            .first()
        )
        if not locked_product or locked_product.stock < item.quantity:
            raise InsufficientStockException(locked_product.name, locked_product.stock, item.quantity)
        locked_product.stock -= item.quantity
    else:
        # Atomic conditional update fallback (SQLite)
        rows_updated = (
            db.query(Product)
            .filter(Product.id == item.product_id, Product.stock >= item.quantity, Product.is_active.is_(True))
            .update({Product.stock: Product.stock - item.quantity}, synchronize_session="fetch")
        )
        if rows_updated == 0:
            raise InsufficientStockException(product.name, product.stock, item.quantity)

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

### 6. Redis 7 Asynchronous Task Processing & Dead Letter Queue (DLQ)

Critical post-order operations (email dispatch, external CRM synchronization, invoice generation) are decoupled from the synchronous HTTP request path using **Redis 7 task lists** (`orders:tasks`) and a dedicated background worker daemon:

```text
 ┌────────────────┐      LPUSH      ┌──────────────────────┐
 │  FastAPI API   ├────────────────►│ Redis Queue          │
 │  (POST /orders)│                 │ (orders:tasks)       │
 └────────────────┘                 └──────────┬───────────┘
                                               │ RPOP
                                               ▼
                                    ┌──────────────────────┐
                                    │  Background Worker   │
                                    │  (app.tasks.worker)  │
                                    └──────────┬───────────┘
                         Success ┌─────────────┴─────────────┐ Failure
                                 ▼                           ▼
                        ┌─────────────────┐        ┌───────────────────┐
                        │ Task Completed  │        │ Retry (Max 3)     │
                        │ & Logged        │        │ Re-enqueued       │
                        └─────────────────┘        └─────────┬─────────┘
                                                             │ Exceeded Retries
                                                             ▼
                                                   ┌───────────────────┐
                                                   │ Dead Letter Queue │
                                                   │ (orders:dlq)      │
                                                   └─────────┬─────────┘
                                                             │ Admin Replay
                                                             ▼
                                                   [Re-enqueued for Reprocessing]
```

- **Resilient Retry Loop:** Failed tasks record failure timestamps and error stack traces, retrying up to `MAX_TASK_RETRIES` (3).
- **Poison Pill Isolation:** If all retries fail, tasks are permanently quarantined into `orders:dlq` without blocking healthy jobs.
- **Admin DLQ APIs:** Administrators can inspect poisoned messages (`GET /api/v1/orders/tasks/dlq`) and replay them (`POST /api/v1/orders/tasks/dlq/{task_id}/reprocess`).
- **Deterministic Testing:** Includes a zero-dependency in-memory queue fallback that simulates Redis operations during local test execution.

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
Places a new order, calculates subtotals, and atomically deducts stock. Supports Stripe-grade duplicate protection via optional `Idempotency-Key` header.

```bash
curl -X POST "http://localhost:8000/api/v1/orders/" \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Idempotency-Key: 9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d" \
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

#### `GET /api/v1/orders/analytics/summary` *(Admin Only)*
Computes financial analytics, Gross Merchandise Value (GMV), average order value (AOV), status breakdown, and top-selling products using optimized SQL aggregations (`func.sum`, `func.count`).

```bash
curl -X GET "http://localhost:8000/api/v1/orders/analytics/summary" \
  -H "Authorization: Bearer <ADMIN_TOKEN>"
```

*Response (200 OK):*
```json
{
  "total_orders": 142,
  "total_revenue": 18450.75,
  "average_order_value": 129.93,
  "status_breakdown": {
    "PENDING": 12,
    "PAID": 45,
    "PROCESSING": 30,
    "SHIPPED": 50,
    "CANCELLED": 5
  },
  "top_selling_products": [
    {
      "product_id": 1,
      "product_name": "Mechanical Wireless Keyboard",
      "units_sold": 94,
      "total_revenue": 8459.06
    }
  ]
}
```

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

## Correlation & Tracing
Requests support distributed tracing via the `X-Request-ID` header.

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

### Running the Test Suite & Coverage

The automated test suite contains **30 tests** covering unit validations, security RBAC boundaries, idempotent checkout retries, promo coupon constraints, order event logs, and **multithreaded race condition simulation**.

```bash
# Run all tests
make test
# Or: pytest -v

# Run with test coverage report (89% coverage)
make test-cov
```

*Test Execution Summary:*
```text
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-9.1.1, pluggy-1.7.0
rootdir: C:\xampp\htdocs\fastapi-orders-api
configfile: pytest.ini
testpaths: tests
plugins: anyio-4.15.1, cov-7.1.0
collected 30 items

tests/test_analytics_and_idempotency.py ....                             [ 13%]
tests/test_auth.py .....                                                 [ 30%]
tests/test_concurrency.py ...                                            [ 40%]
tests/test_coupons_and_events.py ......                                  [ 60%]
tests/test_health.py ..                                                  [ 66%]
tests/test_orders.py .....                                               [ 83%]
tests/test_products.py .....                                             [100%]

=============================== tests coverage ================================
Name                            Stmts   Miss  Cover
---------------------------------------------------
app/api/v1/__init__.py             12      0   100%
app/api/v1/auth.py                 31      1    97%
app/api/v1/coupons.py              40      8    80%
app/api/v1/orders.py               67     14    79%
app/api/v1/products.py             45      7    84%
app/config.py                      23      2    91%
app/core/exceptions.py             20      1    95%
app/core/security.py               28      4    86%
app/database.py                    21      4    81%
app/main.py                        45      4    91%
app/models/coupon.py               40      3    92%
app/models/order.py                54      2    96%
app/schemas/order.py               58      0   100%
app/services/order_service.py      91      6    93%
---------------------------------------------------
TOTAL                             751     82    89%
======================== 30 passed in ~9.5s ========================
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

### Option B: Docker Compose (Production Topology Mirror)

To run the full production stack including **PostgreSQL 16**, **Redis 7**, the **FastAPI REST API**, and the **Asynchronous Background Worker**:

```bash
docker compose up --build
```

The stack orchestrates:
- **`nova_commerce_api`:** FastAPI web service on port `8000`.
- **`nova_commerce_worker`:** Background worker consuming the `orders:tasks` queue.
- **`nova_commerce_db`:** PostgreSQL 16 on port `5432` with healthcheck and volume persistence.
- **`nova_commerce_redis`:** Redis 7 on port `6379` with healthcheck and AOF persistence (`--appendonly yes`).

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















