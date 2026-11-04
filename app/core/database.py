from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.core.config import settings

# Engine configuration
connect_args = {}
engine_kwargs = {
    "pool_pre_ping": True,
    "echo": False,
}

if settings.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False
else:
    # High-concurrency production connection pool tuning for PostgreSQL & PgBouncer
    engine_kwargs.update({
        "pool_size": 40,       # Persistent pool of active connections per worker (80 total across 2 workers)
        "max_overflow": 60,    # Surge buffer supporting up to 200 concurrent DB queries
        "pool_timeout": 30,    # Generous timeout for high-concurrency peak traffic
        "pool_recycle": 1800,  # Recycle connection after 30 mins
    })

engine_kwargs["connect_args"] = connect_args
engine = create_engine(settings.DATABASE_URL, **engine_kwargs)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency yielding an atomic database session.
    Ensures any open transaction is cleanly rolled back before returning the
    connection to the pool, preventing 'idle in transaction' connection/RAM leaks.
    """
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        try:
            if db.is_active:
                db.rollback()
        except Exception:
            pass
        db.close()


def init_db() -> None:
    """
    Creates all database tables based on registered models,
    and applies safe backward-compatible column migrations.
    """
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=engine)

    is_sqlite = settings.DATABASE_URL.startswith("sqlite")
    owner_col_def = "owner_id CHAR(36)" if is_sqlite else "owner_id UUID"
    customer_col_def = "customer_id CHAR(36)" if is_sqlite else "customer_id UUID"

    # Safe migration for new columns on existing database
    migrations = [
        "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS total_cashback_amount NUMERIC(12, 2) DEFAULT 0.00 NOT NULL;",
        "ALTER TABLE transaction_items ADD COLUMN IF NOT EXISTS cashback_amount NUMERIC(12, 2) DEFAULT 0.00 NOT NULL;",
        "ALTER TABLE transaction_items ADD COLUMN IF NOT EXISTS cashback_pct NUMERIC(5, 2) DEFAULT 0.00 NOT NULL;",
        "ALTER TABLE transaction_items ADD COLUMN IF NOT EXISTS discount_amount NUMERIC(12, 2) DEFAULT 0.00 NOT NULL;",
        "ALTER TABLE transaction_items ADD COLUMN IF NOT EXISTS discount_pct NUMERIC(5, 2) DEFAULT 0.00 NOT NULL;",
        "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS received_amount NUMERIC(12, 2) DEFAULT 0.00 NOT NULL;",
        "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS balance_amount NUMERIC(12, 2) DEFAULT 0.00 NOT NULL;",
        "ALTER TABLE stores ADD COLUMN IF NOT EXISTS state VARCHAR(100) DEFAULT '19-West Bengal' NOT NULL;",
        f"ALTER TABLE stores ADD COLUMN IF NOT EXISTS {owner_col_def};",
        "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS invoice_seq INTEGER;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS google_sub VARCHAR(255);",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS picture_url VARCHAR(500);",
        f"ALTER TABLE transactions ADD COLUMN IF NOT EXISTS {customer_col_def};",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS discount_value NUMERIC(12, 2) DEFAULT 0.00 NOT NULL;",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS discount_type VARCHAR(20) DEFAULT 'percentage' NOT NULL;",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS cashback_value NUMERIC(12, 2) DEFAULT 0.00 NOT NULL;",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS cashback_type VARCHAR(20) DEFAULT 'percentage' NOT NULL;",
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS advance_balance NUMERIC(12, 2) DEFAULT 0.00 NOT NULL;",
    ]

    with engine.begin() as conn:
        for stmt in migrations:
            try:
                if is_sqlite:
                    # SQLite does not support IF NOT EXISTS in ADD COLUMN; strip it and ignore duplicate column error
                    clean_stmt = stmt.replace("IF NOT EXISTS ", "").replace(";", "")
                    conn.execute(text(clean_stmt))
                else:
                    conn.execute(text(stmt))
            except Exception:
                # Column likely already exists
                pass

        if not is_sqlite:
            try:
                conn.execute(text("ALTER TABLE stores ALTER COLUMN owner_id TYPE UUID USING owner_id::uuid;"))
            except Exception:
                pass

        try:
            conn.execute(
                text("CREATE UNIQUE INDEX IF NOT EXISTS uq_transactions_store_invoice_seq ON transactions (store_id, invoice_seq);")
            )
            conn.execute(
                text("CREATE UNIQUE INDEX IF NOT EXISTS uq_transactions_store_invoice_num ON transactions (store_id, invoice_number);")
            )
            if not is_sqlite:
                # Drop legacy global unique index on invoice_number to support per-store sequential invoicing
                conn.execute(text("DROP INDEX IF EXISTS ix_transactions_invoice_number;"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_transactions_invoice_number ON transactions (invoice_number);"))
        except Exception:
            pass

        try:
            if is_sqlite:
                conn.execute(
                    text(
                        "CREATE TABLE IF NOT EXISTS customer_stores ("
                        "customer_id CHAR(36) NOT NULL, "
                        "store_id CHAR(36) NOT NULL, "
                        "PRIMARY KEY (customer_id, store_id)"
                        ");"
                    )
                )
                conn.execute(
                    text(
                        "INSERT OR IGNORE INTO customer_stores (customer_id, store_id) "
                        "SELECT customer_id, store_id FROM customers WHERE store_id IS NOT NULL;"
                    )
                )
            else:
                conn.execute(
                    text(
                        "CREATE TABLE IF NOT EXISTS customer_stores ("
                        "customer_id UUID NOT NULL, "
                        "store_id UUID NOT NULL, "
                        "PRIMARY KEY (customer_id, store_id)"
                        ");"
                    )
                )
                conn.execute(
                    text(
                        "INSERT INTO customer_stores (customer_id, store_id) "
                        "SELECT customer_id, store_id FROM customers WHERE store_id IS NOT NULL "
                        "ON CONFLICT DO NOTHING;"
                    )
                )
        except Exception:
            pass

    # Backfill missing invoice_seq on existing transactions per store
    from app.models.transaction import Transaction

    with SessionLocal() as db:
        try:
            unassigned_stores = db.query(Transaction.store_id).filter(Transaction.invoice_seq.is_(None)).distinct().all()
            for (st_id,) in unassigned_stores:
                store_txs = db.query(Transaction).filter(Transaction.store_id == st_id).order_by(Transaction.created_at.asc()).all()
                for idx, tx in enumerate(store_txs, start=1):
                    if tx.invoice_seq is None:
                        tx.invoice_seq = idx
                        if not tx.invoice_number or tx.invoice_number.startswith("INV-20"):
                            tx.invoice_number = f"INV-{idx:05d}"
                db.commit()
        except Exception:
            db.rollback()

    # Backfill missing owner_id on existing stores if empty
    from app.models.store import Store
    from app.models.user import User

    with SessionLocal() as db:
        try:
            stores_without_owner = db.query(Store).filter(Store.owner_id.is_(None)).all()
            for st in stores_without_owner:
                matched_user = None
                if st.email:
                    matched_user = db.query(User).filter(User.email == st.email).first()
                if not matched_user and st.owner_name:
                    matched_user = db.query(User).filter(User.name == st.owner_name).first()
                if not matched_user and st.users_with_access:
                    admin_user = next((u for u in st.users_with_access if u.is_admin()), None)
                    matched_user = admin_user or st.users_with_access[0]
                if matched_user:
                    st.owner_id = matched_user.user_id
                    if matched_user not in st.users_with_access:
                        st.users_with_access.append(matched_user)
            db.commit()
        except Exception:
            db.rollback()

    # Pre-seed Indian States & Union Territories reference table if empty from database seed fixture
    import json
    import os

    from app.models.state import IndianState

    with SessionLocal() as db:
        try:
            count = db.query(IndianState).count()
            if count == 0:
                seed_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "db", "seeds", "indian_states.json")
                if os.path.exists(seed_file):
                    with open(seed_file, encoding="utf-8") as f:
                        states_data = json.load(f)
                    for st in states_data:
                        db.add(
                            IndianState(
                                code=st["code"],
                                name=st["name"],
                                state_type=st["state_type"],
                                display_name=st["display_name"],
                            )
                        )
                    db.commit()
        except Exception:
            db.rollback()
