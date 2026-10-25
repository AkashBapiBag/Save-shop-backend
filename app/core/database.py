from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.core.config import settings

# Engine configuration
connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency yielding an atomic database session.
    Automatically commits on normal completion or rolls back on unhandled error.
    """
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """
    Creates all database tables based on registered models,
    and applies safe backward-compatible column migrations.
    """
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=engine)

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
        "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS invoice_seq INTEGER;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS google_sub VARCHAR(255);",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS picture_url VARCHAR(500);",
    ]

    is_sqlite = settings.DATABASE_URL.startswith("sqlite")
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

        try:
            conn.execute(
                text("CREATE UNIQUE INDEX IF NOT EXISTS uq_transactions_store_invoice_seq ON transactions (store_id, invoice_seq);")
            )
            conn.execute(
                text("CREATE UNIQUE INDEX IF NOT EXISTS uq_transactions_store_invoice_num ON transactions (store_id, invoice_number);")
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
