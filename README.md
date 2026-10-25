# 🏪 Save Shop Backend API

High-performance, production-grade REST API backend for the **Save Shop Inventory and Billing Management System**, built with **FastAPI**, **SQLAlchemy 2.0**, **Pydantic v2**, and **PostgreSQL** (with zero-configuration SQLite support for rapid local development and testing).

---

## 🏛️ System Architecture & Best Practices

```
backend/
├── app/
│   ├── main.py                     # FastAPI application factory, CORS, exception handlers, lifespans
│   ├── core/
│   │   ├── config.py               # Pydantic Settings (.env configuration)
│   │   ├── database.py             # SQLAlchemy 2.0 session engine and table initialization
│   │   ├── security.py             # Auth0 SSO JWT verification and internal HS256 tokens
│   │   ├── dependencies.py         # Injected security dependencies (Admin check, Store context)
│   │   └── exceptions.py           # Standardized application exception hierarchy
│   ├── models/                     # SQLAlchemy ORM Models (PostgreSQL UUID & BYTEA support)
│   │   ├── user.py                 # User, UserRole, UserStoreAccess (Many-to-Many)
│   │   ├── store.py                # Store entity with BYTEA authorized signature & logo
│   │   ├── inventory.py            # Product & Batch (FEFO tracking, current_quantity)
│   │   ├── transaction.py          # POS Transaction, TransactionItem, BatchAllocation
│   │   └── notification.py         # Google Trigger & alert logs
│   ├── schemas/                    # Strict Pydantic v2 validation models
│   │   ├── common.py               # Standard response envelopes and error payloads
│   │   ├── auth.py                 # Login, tokens, store switching schemas
│   │   ├── store.py                # Store CRUD, signature upload/download
│   │   ├── inventory.py            # Product CRUD, single/bulk batch receiving, units
│   │   ├── billing.py              # POS checkout, 3-tier discounts, structured receipt, offline sync
│   │   └── dashboard.py            # Overview KPIs, Stock Health, Sales Velocity, Inventory Status
│   ├── services/                   # Business Logic & Core Workflows
│   │   ├── auth_service.py         # SSO identity sync, role enforcement, store context switching
│   │   ├── store_service.py        # Store metadata & critical pre-save transaction count check
│   │   ├── inventory_service.py    # Catalog management, atomic single/bulk batch ingestion
│   │   ├── pos_service.py          # POS Core Loop (3-tier discounts, FEFO stock deduction, receipt builder)
│   │   ├── dashboard_service.py    # Aggregated metrics (30/60 days expiry, sales velocity)
│   │   └── notification_service.py # Google Trigger mechanism & low stock alerts
│   └── api/
│       └── v1/
│           ├── router.py           # v1 Router aggregate
│           └── endpoints/          # Route handlers for each service module
├── tests/                          # 100% automated test coverage (Pytest + In-Memory SQLite)
├── .env.example
├── Dockerfile
└── docker-compose.yml
```

---

## 🎯 Implementation of Key Technical Requirements

### 1. Authentication Service (`AuthService`)
* **Auth0 SSO via Google Identity Provider:**
  * In production (`AUTH0_ENABLED=True`), incoming Bearer tokens are cryptographically verified against Auth0's JWKS endpoint (`/.well-known/jwks.json`) with audience and issuer verification.
  * In local development or testing (`AUTH0_ENABLED=False`), a built-in mock token generator and header bypass (`X-Dev-User-Email`) allow full local testing without requiring active internet or Auth0 credentials.
* **Role Enforcement:**
  * Differentiates between `Admin` and `Standard User` (`User`).
  * Only `Admin` can create stores or assign store permissions.
  * `User` role can only switch context between approved stores assigned to them in `user_store_access`.

### 2. Store Management Service (`StoreService`)
* **Data Model:**
  * `store_id`: UUID Primary Key.
  * `name`: Unique Index.
  * `phone_number`, `address`, `email`, `logo_url`.
  * `authorized_signature_data`: Binary `BYTEA` / `BLOB` for secure storage of the authorized signature image.
* **Critical Constraint (Store Creation):**
  * When attempting to create a new store (`POST /api/v1/stores/create`), a pre-save check executes:
    ```sql
    SELECT COUNT(*) FROM transactions WHERE store_id = :new_store_id
    ```
    If any existing transactions are linked to this store ID, store creation is rejected with a `STORE_CREATION_INTEGRITY_VIOLATION` (HTTP 409 Conflict).

### 3. Inventory Service (`InventoryService`)
* **Product Catalog:**
  * Complete categorization, customizable units (`KG`, `ML`, `GRAM`, `DOZEN`, `PIECE`, `LITER`, `PACKET`, `BOX`, `BOTTLE`, `CAN`, `METER`).
  * Configurable `min_stock_alert_threshold` per product.
* **Batch-wise Inventory Control:**
  * Source of truth for inventory is the sum of `current_quantity` across active batches.
  * Atomic stock ingestion workflows:
    1. **`POST /api/v1/inventory/receive/single`**: Single lot ingestion.
    2. **`POST /api/v1/inventory/receive/bulk`**: Multi-batch atomic ingestion requiring `batch_identifier`, `quantity`, `purchase_date`, and `expiry_date`.
  * Validates that `expiry_date >= purchase_date`.

### 4. Billing & Point-of-Sale (POS) Service (`POSService`)
* **The POS Core Transaction Loop:**
  1. **Input:** Products and quantities requested.
  2. **Base Calculation:** `Base Total = Quantity * UnitPrice`.
  3. **Priority Discount Hierarchy:**
     * **Item Level:** Percentage discount on individual product item.
     * **Product Type / Category Level:** Percentage discount on the product's category.
     * **Subtotal Total Level:** Percentage discount on the calculated subtotal.
     * **Final Total:** `Base Total - Item Discounts - Total Discount`.
  4. **FEFO (First-Expiry, First-Out) Inventory Deduction:**
     * Discovers all positive batches ordered by `expiry_date ASC, purchase_date ASC`.
     * Validates that total positive stock >= requested quantity.
     * If insufficient: rolls back immediately and raises `INSUFFICIENT_STOCK` (HTTP 400).
     * Deducts stock in strict FEFO sequence and records `TransactionBatchAllocation` entries for full traceability.
  5. **Low Stock Alerts:** Automatically triggers notification if stock falls below threshold.
* **Structured Receipt Endpoint (`GET /api/v1/billing/transactions/{id}/receipt`):**
  * Returns complete structured data (Store logo, address, phone, authorized signature in base64, itemized line breakdown, discounts, invoice number, and cashier details) designed specifically for client-side React Native PDF generation and Android `PrintManager`.
* **Offline Mode Synchronization (`POST /api/v1/billing/sync`):**
  * Accepts a batch of offline-recorded transactions.
  * Idempotent based on `client_offline_id`.
  * Deducts FEFO inventory per transaction and reports detailed status (`synced`, `already_synced`, `failed_insufficient_stock`).

### 5. Dashboard & Reporting Service (`DashboardService`)
* **Real-time Aggregation:**
  * `GET /api/v1/dashboard/overview`: Today's revenue, weekly revenue, monthly revenue, transaction counts, low-stock count, and expiry counts.
  * `GET /api/v1/dashboard/stock-health`: Pinpoints batches nearing expiry (within 30 and 60 days) and expired batches.
  * `GET /api/v1/dashboard/sales-velocity`: Top N selling items and daily revenue trend.
  * `GET /api/v1/dashboard/inventory-status`: Real-time stock counts and out-of-stock warnings.

### 6. Notifications & Google Trigger Integration (`NotificationService`)
* Webhook receiver (`POST /api/v1/notifications/google-trigger`) for Google Cloud Tasks / Cloud Functions trigger callbacks.
* Notification dispatcher for low-stock warnings, payment confirmations, WhatsApp/Email simulation logs.

---

## 🚀 Getting Started

### 1. Prerequisites
* Python 3.10+ (or Python 3.11 / 3.15)
* Virtual environment (`.venv`)

### 2. Quick Run (Local Development)
```bash
# In the backend directory
# 1. Activate virtual environment
.venv\Scripts\activate   # Windows
# or: source .venv/bin/activate  # Linux/macOS

# 2. Run with uvicorn
uvicorn app.main:app --reload --port 8000
```

### 3. Running with Docker Compose (PostgreSQL + FastAPI)
```bash
docker-compose up --build
```

### 4. Interactive API Documentation
* **Swagger UI:** [http://localhost:8000/docs](http://localhost:8000/docs)
* **ReDoc:** [http://localhost:8000/redoc](http://localhost:8000/redoc)
* **Health Check:** [http://localhost:8000/health](http://localhost:8000/health)

---

## 🧪 Running Automated Tests

A comprehensive Pytest suite is included covering Authentication, Store Pre-Save Constraints, FEFO Stock Depletion, 3-Tier Discounts, and Dashboard Reporting.

```bash
# Run all tests
pytest tests -v
```

Output:
```
tests/test_auth.py::test_auth_login_admin PASSED
tests/test_auth.py::test_auth_me PASSED
tests/test_auth.py::test_user_store_switching_restriction PASSED
tests/test_billing_pos.py::test_pos_fefo_stock_depletion PASSED
tests/test_billing_pos.py::test_pos_3_tier_discounts_calculation PASSED
tests/test_billing_pos.py::test_pos_insufficient_stock_rollback PASSED
tests/test_billing_pos.py::test_pos_structured_receipt_endpoint PASSED
tests/test_billing_pos.py::test_pos_offline_sync PASSED
tests/test_dashboard.py::test_dashboard_reporting_flows PASSED
tests/test_inventory.py::test_product_crud_and_stock_calculation PASSED
tests/test_inventory.py::test_bulk_batch_receiving PASSED
tests/test_inventory.py::test_batch_date_validation_rejects_past_expiry PASSED
tests/test_stores.py::test_create_store_admin PASSED
tests/test_stores.py::test_create_store_forbidden_for_standard_user PASSED
tests/test_stores.py::test_create_store_presave_constraint_with_existing_transactions PASSED
tests/test_stores.py::test_store_signature_upload_and_retrieval PASSED

======================== 16 passed in 0.74s ========================
```
