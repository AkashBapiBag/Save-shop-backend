"""
Comprehensive Seed & Database Reset Script for Save Shop Management System
Populates local database (PostgreSQL or SQLite) with realistic, end-to-end data
to test ALL features and edge cases across the entire application:
- Authentication & Roles (Admin, Manager, Cashier, Google SSO, Direct Dev Login)
- Multi-Store Architecture (Flagship, S-Mart Branch, Central Store, store switching)
- Store Operators & Invitations (Pending, Accepted, Revoked)
- Customer Directory & CRM (Phone book search, purchase history, multi-store sharing, Khata/Credit tracking)
- POS Terminal & Checkout (Cash with change, UPI, Card, Credit/Khata pending)
- Tax Invoicing & Barcode Scanning (EAN-13 barcodes, sequential invoices, PDF print)
- Product Discounts (Percentage & Fixed) and Cashback (Percentage & Fixed)
- Comprehensive Unit Variety (KG, GRAM, LITER, ML, PACKET, BOX, PIECE, BOTTLE, CAN)
- Multi-Batch FEFO Inventory (Fresh, Near-expiry alert, Expired alert, Depleted)
- Stock Status Conditions (Healthy, Low Stock < threshold, Out-of-Stock = 0)
- Inter-Store Stock Transfers (Outward, Inward, auto-created products)
- Dashboard Analytics (Today's revenue, Weekly trends, Monthly totals, Top-selling products, Stock health)
- System Notification Logs (Expiry warning, Low stock, POS payment, Transfer alert)
- Indian States GST Reference Table (all 36 States & Union Territories)
"""

import argparse
import json
import os
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

# Ensure backend root is on sys.path
backend_dir = Path(__file__).resolve().parent.parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal, engine, init_db
from app.models.customer import Customer, customer_stores
from app.models.inventory import Batch, Product, UnitEnum
from app.models.invitation import StoreInvitation
from app.models.notification import (
    NotificationChannel,
    NotificationEvent,
    NotificationLog,
)
from app.models.state import IndianState
from app.models.stock_transfer import StockTransfer, StockTransferItem
from app.models.store import Store
from app.models.transaction import (
    PaymentMethod,
    PaymentStatus,
    Transaction,
    TransactionBatchAllocation,
    TransactionItem,
)
from app.models.user import User, user_store_access


def clean_database():
    """
    Cleans up the entire local database, removing all existing rows across all
    application tables and resetting sequences. Handles foreign key dependencies cleanly.
    """
    print("[1/10] Cleaning up full local database...")
    is_sqlite = settings.DATABASE_URL.startswith("sqlite")

    with engine.begin() as conn:
        if is_sqlite:
            conn.execute(text("PRAGMA foreign_keys = OFF;"))
            tables_to_clean = [
                "transaction_batch_allocations",
                "transaction_items",
                "transactions",
                "stock_transfer_items",
                "stock_transfers",
                "store_invitations",
                "customer_stores",
                "customers",
                "user_store_access",
                "batches",
                "products",
                "notification_logs",
                "users",
                "stores",
            ]
            for tbl in tables_to_clean:
                try:
                    conn.execute(text(f"DELETE FROM {tbl};"))
                except Exception as e:
                    print(f"  Warning deleting from {tbl}: {e}")
            conn.execute(text("PRAGMA foreign_keys = ON;"))
        else:
            # PostgreSQL TRUNCATE CASCADE with identity restart
            conn.execute(
                text(
                    """
                    TRUNCATE TABLE 
                        transaction_batch_allocations,
                        transaction_items,
                        transactions,
                        stock_transfer_items,
                        stock_transfers,
                        store_invitations,
                        customer_stores,
                        customers,
                        user_store_access,
                        batches,
                        products,
                        notification_logs,
                        users,
                        stores
                    RESTART IDENTITY CASCADE;
                    """
                )
            )

    print("  -> Full local database cleanly wiped.")


def seed_database(clean: bool = True):
    """
    Seeds pristine, comprehensive data to test all the things in Save Shop.
    """
    if clean:
        clean_database()

    print("[2/10] Initializing database tables, indexes, and reference migrations...")
    init_db()

    with SessionLocal() as db:
        print("[3/10] Setting up Users & Roles...")
        # 1. Primary Owner & Super Admin (Akash Bag)
        admin_email = "akashbapibag9@gmail.com"
        admin_user = User(
            user_id=uuid.UUID("34e82069-2b66-43da-beca-de6cd808f1a0"),
            email=admin_email,
            name="Akash Bag",
            role="admin",
            is_active=True,
        )
        db.add(admin_user)

        # 2. Secondary Admin / Branch Manager
        sec_admin_email = "akashbapibag4582@gmail.com"
        sec_admin_user = User(
            user_id=uuid.UUID("0176b937-75e5-4209-aa54-0d63ebdd776e"),
            email=sec_admin_email,
            name="Akash Bag (Branch Mgr)",
            role="admin",
            is_active=True,
        )
        db.add(sec_admin_user)

        # 3. Default General Admin
        gen_admin_email = "admin@saveshop.com"
        gen_admin_user = User(
            user_id=uuid.UUID("824d56f2-7c4c-4044-9c21-099e59665f82"),
            email=gen_admin_email,
            name="Save Shop Administrator",
            role="admin",
            is_active=True,
        )
        db.add(gen_admin_user)

        # 4. Flagship Store POS Cashier / Operator
        clerk_email = "clerk@saveshop.com"
        clerk_user = User(
            user_id=uuid.UUID("35e7b7e9-65e1-49e8-882a-70e980aab60f"),
            email=clerk_email,
            name="Ramesh Clerk",
            role="user",
            is_active=True,
        )
        db.add(clerk_user)

        # 5. S-Mart Store POS Cashier
        cashier_email = "cashier@saveshop.com"
        cashier_user = User(
            user_id=uuid.UUID("8ace3f7c-477a-43c1-8c68-480d0e887fac"),
            email=cashier_email,
            name="Sita Sharma",
            role="user",
            is_active=True,
        )
        db.add(cashier_user)

        db.flush()

        print("[4/10] Setting up Multi-Store Architecture...")
        # Store 1: Flagship Store (Salt Lake)
        flagship = Store(
            store_id=uuid.UUID("c0e66522-1b0b-408c-8366-c0fe083f2a23"),
            name="Local Save Shop Flagship",
            owner_id=admin_user.user_id,
            owner_name="Akash Bag",
            phone_number="+91 98300 12345",
            address="Plot 14, Block EP & GP, Sector V, Salt Lake, Kolkata, West Bengal - 700091",
            state="19-West Bengal",
            email="flagship@saveshop.com",
            is_active=True,
        )
        db.add(flagship)

        # Store 2: S-Mart Branch (New Town)
        smart = Store(
            store_id=uuid.UUID("ade6957e-d145-4a1b-b772-624c9b92956c"),
            name="S-Mart",
            owner_id=admin_user.user_id,
            owner_name="Akash Bag",
            phone_number="+91 98311 54321",
            address="Premises 20, Major Arterial Road, New Town Action Area I, Kolkata, West Bengal - 700156",
            state="19-West Bengal",
            email="smart.branch@saveshop.com",
            is_active=True,
        )
        db.add(smart)

        # Store 3: Central Branch (Park Street)
        central = Store(
            store_id=uuid.UUID("d5f81a20-4e3b-417c-a81d-e59273c88120"),
            name="Save Shop Central (Park Street)",
            owner_id=admin_user.user_id,
            owner_name="Akash Bag",
            phone_number="+91 98322 98765",
            address="54A Park Street, Mullick Bazar, Park Street Area, Kolkata, West Bengal - 700016",
            state="19-West Bengal",
            email="central.parkstreet@saveshop.com",
            is_active=True,
        )
        db.add(central)

        db.flush()

        # Link operator store permissions
        def grant_store_access(u: User, s: Store):
            db.execute(user_store_access.insert().values(user_id=u.user_id, store_id=s.store_id))

        grant_store_access(admin_user, flagship)
        grant_store_access(admin_user, smart)
        grant_store_access(admin_user, central)

        grant_store_access(sec_admin_user, flagship)
        grant_store_access(sec_admin_user, smart)

        grant_store_access(gen_admin_user, flagship)
        grant_store_access(gen_admin_user, smart)
        grant_store_access(gen_admin_user, central)

        grant_store_access(clerk_user, flagship)
        grant_store_access(cashier_user, smart)

        # Set active store contexts
        admin_user.current_store_id = flagship.store_id
        sec_admin_user.current_store_id = smart.store_id
        gen_admin_user.current_store_id = flagship.store_id
        clerk_user.current_store_id = flagship.store_id
        cashier_user.current_store_id = smart.store_id

        db.commit()

        print("[5/10] Setting up Store Invitations & Operator Workflow...")
        invitations_data = [
            (flagship.store_id, "assistant.manager@saveshop.com", "admin", "pending"),
            (flagship.store_id, "cashier.saltlake@saveshop.com", "user", "pending"),
            (flagship.store_id, clerk_email, "user", "accepted"),
            (flagship.store_id, "former.clerk@saveshop.com", "user", "revoked"),
            (smart.store_id, "smart.cashier@example.com", "user", "pending"),
        ]
        for st_id, inv_email, inv_role, inv_status in invitations_data:
            db.add(
                StoreInvitation(
                    invitation_id=uuid.uuid4(),
                    store_id=st_id,
                    email=inv_email,
                    role=inv_role,
                    status=inv_status,
                    invited_by_id=admin_user.user_id,
                )
            )
        db.commit()

        print("[6/10] Setting up Customer Directory & CRM Profiles...")
        customers_def = [
            {
                "name": "Akash Bag",
                "phone": "7688044501",
                "email": "akashbapibag9@gmail.com",
                "address": "Salt Lake Sector V, Kolkata, WB - 700091",
                "notes": "Store Owner & VIP Customer",
                "multi_store": True,
            },
            {
                "name": "Rahul Sharma",
                "phone": "9876543210",
                "email": "rahul.sharma@example.com",
                "address": "Block AE, Salt Lake, Kolkata - 700064",
                "notes": "Regular Customer - Fast UPI checkout",
                "multi_store": True,
            },
            {
                "name": "Priya Patel",
                "phone": "9823456789",
                "email": "priya.patel@example.com",
                "address": "Park Street, Kolkata - 700016",
                "notes": "Weekly buyer - Dairy & Fresh produce",
                "multi_store": False,
            },
            {
                "name": "Amit Ghosh",
                "phone": "9830123456",
                "email": "amit.ghosh@example.com",
                "address": "Howrah, WB - 711101",
                "notes": "Wholesale & Catering buyer - High ticket size",
                "multi_store": False,
            },
            {
                "name": "Sunita Devi",
                "phone": "9748554433",
                "email": "sunita.devi@example.com",
                "address": "New Town Action Area II, Kolkata - 700156",
                "notes": "Daily Cash on counter customer",
                "multi_store": False,
            },
            {
                "name": "Vikram Malhotra",
                "phone": "9811223344",
                "email": "vikram.m@example.com",
                "address": "Ballygunge Circular Road, Kolkata - 700019",
                "notes": "Khata / Credit customer (Monthly settlement with pending balance)",
                "multi_store": False,
            },
            {
                "name": "Sneha Roy",
                "phone": "9871122334",
                "email": "sneha.roy@example.com",
                "address": "Dum Dum Park, Kolkata - 700055",
                "notes": "Newly registered customer - Zero transactions state test",
                "multi_store": False,
            },
            {
                "name": "Rajesh Gupta",
                "phone": "9831987654",
                "email": "rajesh.gupta@example.com",
                "address": "Action Area I, New Town, Kolkata - 700156",
                "notes": "S-Mart branch regular customer",
                "multi_store": False,
                "primary_smart": True,
            },
            {
                "name": "Ananya Sen",
                "phone": "9832109876",
                "email": "ananya.sen@example.com",
                "address": "Salt Lake Sector I, Kolkata - 700064",
                "notes": "Personal care & snacks shopper",
                "multi_store": True,
            },
        ]

        customer_map: dict[str, Customer] = {}
        for cdata in customers_def:
            p_store = smart.store_id if cdata.get("primary_smart") else flagship.store_id
            cust = Customer(
                customer_id=uuid.uuid4(),
                store_id=p_store,
                name=cdata["name"],
                phone=cdata["phone"],
                email=cdata["email"],
                address=cdata["address"],
                notes=cdata["notes"],
            )
            db.add(cust)
            db.flush()

            # Primary link in customer_stores
            db.execute(customer_stores.insert().values(customer_id=cust.customer_id, store_id=p_store))

            # Multi-store secondary link
            if cdata.get("multi_store"):
                sec_store = flagship.store_id if p_store == smart.store_id else smart.store_id
                db.execute(customer_stores.insert().values(customer_id=cust.customer_id, store_id=sec_store))

            customer_map[cdata["name"]] = cust

        db.commit()

        print("[7/10] Setting up Product Catalog & Multi-Batch FEFO Inventory...")
        today = date.today()

        # 29 Comprehensive products across all categories and units
        flagship_products_def = [
            # 1. Grocery & Staples
            {
                "name": "Daawat Rozana Super Basmati Rice (5 KG)",
                "category": "Grocery & Staples",
                "default_unit": UnitEnum.KG.value,
                "sp": Decimal("399.00"),
                "cost": Decimal("320.00"),
                "barcode": "8901537001052",
                "discount_value": Decimal("10.00"),
                "discount_type": "percentage",
                "cashback_value": Decimal("0.00"),
                "cashback_type": "percentage",
                "min_stock": Decimal("15.000"),
                "batches": [
                    {
                        "num": "DAAW-RICE-202609-A",
                        "qty": Decimal("15.000"),
                        "init": Decimal("20.000"),
                        "expiry": today + timedelta(days=280),
                        "cost": Decimal("310.00"),
                        "purchase": today - timedelta(days=50),
                    },
                    {
                        "num": "DAAW-RICE-202610-B",
                        "qty": Decimal("25.000"),
                        "init": Decimal("25.000"),
                        "expiry": today + timedelta(days=340),
                        "cost": Decimal("325.00"),
                        "purchase": today - timedelta(days=15),
                    },
                ],
            },
            {
                "name": "Aashirvaad Shudh Chakki Atta (10 KG)",
                "category": "Grocery & Staples",
                "default_unit": UnitEnum.PACKET.value,
                "sp": Decimal("435.00"),
                "cost": Decimal("380.00"),
                "barcode": "8901725181222",
                "discount_value": Decimal("5.00"),
                "discount_type": "percentage",
                "cashback_value": Decimal("0.00"),
                "cashback_type": "percentage",
                "min_stock": Decimal("10.000"),
                "batches": [
                    {
                        "num": "AASH-ATT-202610-A",
                        "qty": Decimal("20.000"),
                        "init": Decimal("25.000"),
                        "expiry": today + timedelta(days=160),
                        "cost": Decimal("375.00"),
                        "purchase": today - timedelta(days=35),
                    },
                    {
                        "num": "AASH-ATT-202611-B",
                        "qty": Decimal("30.000"),
                        "init": Decimal("30.000"),
                        "expiry": today + timedelta(days=200),
                        "cost": Decimal("385.00"),
                        "purchase": today - timedelta(days=5),
                    },
                ],
            },
            {
                "name": "Tata Salt Vacuum Evaporated (1 KG)",
                "category": "Grocery & Staples",
                "default_unit": UnitEnum.PACKET.value,
                "sp": Decimal("25.00"),
                "cost": Decimal("20.00"),
                "barcode": "8901030383748",
                "discount_value": Decimal("0.00"),
                "discount_type": "percentage",
                "cashback_value": Decimal("0.00"),
                "cashback_type": "percentage",
                "min_stock": Decimal("20.000"),
                "batches": [
                    {
                        "num": "TATA-SALT-001",
                        "qty": Decimal("50.000"),
                        "init": Decimal("60.000"),
                        "expiry": today + timedelta(days=580),
                        "cost": Decimal("20.00"),
                        "purchase": today - timedelta(days=25),
                    },
                ],
            },
            {
                "name": "Fortune Sunlite Refined Sunflower Oil (1 LITER)",
                "category": "Grocery & Staples",
                "default_unit": UnitEnum.BOTTLE.value,
                "sp": Decimal("148.00"),
                "cost": Decimal("125.00"),
                "barcode": "8906007281234",
                "discount_value": Decimal("10.00"),
                "discount_type": "fixed",
                "cashback_value": Decimal("0.00"),
                "cashback_type": "percentage",
                "min_stock": Decimal("10.000"),
                "batches": [
                    {
                        "num": "FORT-OIL-BATCH1",
                        "qty": Decimal("25.000"),
                        "init": Decimal("30.000"),
                        "expiry": today + timedelta(days=230),
                        "cost": Decimal("125.00"),
                        "purchase": today - timedelta(days=30),
                    },
                ],
            },
            {
                "name": "Tata Sampann Unpolished Toor Dal (1 KG)",
                # Low stock condition (qty 4 < threshold 10) to test low-stock indicator
                "category": "Grocery & Staples",
                "default_unit": UnitEnum.PACKET.value,
                "sp": Decimal("172.00"),
                "cost": Decimal("150.00"),
                "barcode": "8901030823411",
                "discount_value": Decimal("0.00"),
                "discount_type": "percentage",
                "cashback_value": Decimal("0.00"),
                "cashback_type": "percentage",
                "min_stock": Decimal("10.000"),
                "batches": [
                    {
                        "num": "TATA-DAL-LOW01",
                        "qty": Decimal("4.000"),
                        "init": Decimal("20.000"),
                        "expiry": today + timedelta(days=260),
                        "cost": Decimal("150.00"),
                        "purchase": today - timedelta(days=22),
                    },
                ],
            },
            {
                "name": "Dhampure Pure White Refined Sugar (1 KG)",
                "category": "Grocery & Staples",
                "default_unit": UnitEnum.PACKET.value,
                "sp": Decimal("48.00"),
                "cost": Decimal("40.00"),
                "barcode": "8906014640017",
                "discount_value": Decimal("0.00"),
                "discount_type": "percentage",
                "cashback_value": Decimal("0.00"),
                "cashback_type": "percentage",
                "min_stock": Decimal("15.000"),
                "batches": [
                    {
                        "num": "DHAM-SUGAR-01",
                        "qty": Decimal("40.000"),
                        "init": Decimal("50.000"),
                        "expiry": today + timedelta(days=400),
                        "cost": Decimal("40.00"),
                        "purchase": today - timedelta(days=20),
                    },
                ],
            },
            {
                "name": "Engine Pure Mustard Oil (1 LITER)",
                "category": "Grocery & Staples",
                "default_unit": UnitEnum.BOTTLE.value,
                "sp": Decimal("165.00"),
                "cost": Decimal("138.00"),
                "barcode": "8906015500013",
                "discount_value": Decimal("10.00"),
                "discount_type": "fixed",
                "cashback_value": Decimal("0.00"),
                "cashback_type": "percentage",
                "min_stock": Decimal("8.000"),
                "batches": [
                    {
                        "num": "ENG-MUST-01",
                        "qty": Decimal("20.000"),
                        "init": Decimal("25.000"),
                        "expiry": today + timedelta(days=270),
                        "cost": Decimal("138.00"),
                        "purchase": today - timedelta(days=18),
                    },
                ],
            },
            # 2. Dairy & Fresh
            {
                "name": "Amul Taaza Fresh Toned Milk (1 LITER)",
                # Near-expiry condition (expiry in 4 days) to test FEFO priority & warning alert
                "category": "Dairy & Fresh",
                "default_unit": UnitEnum.LITER.value,
                "sp": Decimal("54.00"),
                "cost": Decimal("48.00"),
                "barcode": "8901262010053",
                "discount_value": Decimal("0.00"),
                "discount_type": "percentage",
                "cashback_value": Decimal("0.00"),
                "cashback_type": "percentage",
                "min_stock": Decimal("10.000"),
                "batches": [
                    {
                        "num": "AMUL-MILK-EXP-SOON",
                        "qty": Decimal("8.000"),
                        "init": Decimal("15.000"),
                        "expiry": today + timedelta(days=4),
                        "cost": Decimal("48.00"),
                        "purchase": today - timedelta(days=2),
                    },
                    {
                        "num": "AMUL-MILK-FRESH",
                        "qty": Decimal("24.000"),
                        "init": Decimal("25.000"),
                        "expiry": today + timedelta(days=14),
                        "cost": Decimal("48.00"),
                        "purchase": today,
                    },
                ],
            },
            {
                "name": "Amul Salted Butter (500g)",
                "category": "Dairy & Fresh",
                "default_unit": UnitEnum.BOX.value,
                "sp": Decimal("260.00"),
                "cost": Decimal("230.00"),
                "barcode": "8901262020014",
                "discount_value": Decimal("15.00"),
                "discount_type": "fixed",
                "cashback_value": Decimal("0.00"),
                "cashback_type": "percentage",
                "min_stock": Decimal("5.000"),
                "batches": [
                    {
                        "num": "AMUL-BUTTER-B1",
                        "qty": Decimal("10.000"),
                        "init": Decimal("15.000"),
                        "expiry": today + timedelta(days=100),
                        "cost": Decimal("225.00"),
                        "purchase": today - timedelta(days=20),
                    },
                    {
                        "num": "AMUL-BUTTER-B2",
                        "qty": Decimal("20.000"),
                        "init": Decimal("20.000"),
                        "expiry": today + timedelta(days=170),
                        "cost": Decimal("232.00"),
                        "purchase": today - timedelta(days=3),
                    },
                ],
            },
            {
                "name": "Mother Dairy Classic Paneer (200g)",
                "category": "Dairy & Fresh",
                "default_unit": UnitEnum.PACKET.value,
                "sp": Decimal("90.00"),
                "cost": Decimal("76.00"),
                "barcode": "8901648001017",
                "discount_value": Decimal("5.00"),
                "discount_type": "fixed",
                "cashback_value": Decimal("0.00"),
                "cashback_type": "percentage",
                "min_stock": Decimal("8.000"),
                "batches": [
                    {
                        "num": "MD-PAN-01",
                        "qty": Decimal("15.000"),
                        "init": Decimal("20.000"),
                        "expiry": today + timedelta(days=20),
                        "cost": Decimal("76.00"),
                        "purchase": today - timedelta(days=2),
                    },
                ],
            },
            {
                "name": "Amul Processed Cheese Slices (200g - 10 Slices)",
                # Out-of-stock condition (qty 0) to test out-of-stock badge & POS validation
                "category": "Dairy & Fresh",
                "default_unit": UnitEnum.PACKET.value,
                "sp": Decimal("140.00"),
                "cost": Decimal("118.00"),
                "barcode": "8901262030013",
                "discount_value": Decimal("0.00"),
                "discount_type": "percentage",
                "cashback_value": Decimal("0.00"),
                "cashback_type": "percentage",
                "min_stock": Decimal("10.000"),
                "batches": [
                    {
                        "num": "AMUL-CHS-DEPLETED",
                        "qty": Decimal("0.000"),
                        "init": Decimal("15.000"),
                        "expiry": today + timedelta(days=120),
                        "cost": Decimal("118.00"),
                        "purchase": today - timedelta(days=40),
                    },
                ],
            },
            # 3. Snacks & Confectionery
            {
                "name": "Lay's India's Magic Masala Chips (50g)",
                # Includes an EXPIRED batch to test expired stock badge and filter
                "category": "Snacks & Confectionery",
                "default_unit": UnitEnum.PACKET.value,
                "sp": Decimal("20.00"),
                "cost": Decimal("16.00"),
                "barcode": "8901491101844",
                "discount_value": Decimal("0.00"),
                "discount_type": "percentage",
                "cashback_value": Decimal("0.00"),
                "cashback_type": "percentage",
                "min_stock": Decimal("25.000"),
                "batches": [
                    {
                        "num": "LAYS-EXP-OLD",
                        "qty": Decimal("3.000"),
                        "init": Decimal("10.000"),
                        "expiry": today - timedelta(days=10),  # Already Expired!
                        "cost": Decimal("15.00"),
                        "purchase": today - timedelta(days=120),
                    },
                    {
                        "num": "LAYS-FRESH-01",
                        "qty": Decimal("45.000"),
                        "init": Decimal("50.000"),
                        "expiry": today + timedelta(days=150),
                        "cost": Decimal("16.00"),
                        "purchase": today - timedelta(days=10),
                    },
                ],
            },
            {
                "name": "Cadbury Dairy Milk Silk Chocolate (150g)",
                "category": "Snacks & Confectionery",
                "default_unit": UnitEnum.PIECE.value,
                "sp": Decimal("160.00"),
                "cost": Decimal("130.00"),
                "barcode": "8901233024898",
                "discount_value": Decimal("10.00"),
                "discount_type": "percentage",
                "cashback_value": Decimal("0.00"),
                "cashback_type": "percentage",
                "min_stock": Decimal("10.000"),
                "batches": [
                    {
                        "num": "CAD-SILK-001",
                        "qty": Decimal("30.000"),
                        "init": Decimal("35.000"),
                        "expiry": today + timedelta(days=290),
                        "cost": Decimal("130.00"),
                        "purchase": today - timedelta(days=15),
                    },
                ],
            },
            {
                "name": "Britannia Good Day Butter Cookies (200g)",
                "category": "Snacks & Confectionery",
                "default_unit": UnitEnum.PACKET.value,
                "sp": Decimal("35.00"),
                "cost": Decimal("28.00"),
                "barcode": "8901063012820",
                "discount_value": Decimal("0.00"),
                "discount_type": "percentage",
                "cashback_value": Decimal("0.00"),
                "cashback_type": "percentage",
                "min_stock": Decimal("15.000"),
                "batches": [
                    {
                        "num": "BRIT-GD-001",
                        "qty": Decimal("35.000"),
                        "init": Decimal("40.000"),
                        "expiry": today + timedelta(days=210),
                        "cost": Decimal("28.00"),
                        "purchase": today - timedelta(days=8),
                    },
                ],
            },
            {
                "name": "Haldiram's Nagpur Bhujia Sev (400g)",
                "category": "Snacks & Confectionery",
                "default_unit": UnitEnum.PACKET.value,
                "sp": Decimal("99.00"),
                "cost": Decimal("80.00"),
                "barcode": "8904063200054",
                "discount_value": Decimal("10.00"),
                "discount_type": "percentage",
                "cashback_value": Decimal("0.00"),
                "cashback_type": "percentage",
                "min_stock": Decimal("12.000"),
                "batches": [
                    {
                        "num": "HALD-BHUJ-01",
                        "qty": Decimal("25.000"),
                        "init": Decimal("30.000"),
                        "expiry": today + timedelta(days=180),
                        "cost": Decimal("80.00"),
                        "purchase": today - timedelta(days=14),
                    },
                ],
            },
            {
                "name": "Parle-G Gold Glucose Biscuits (1 KG)",
                "category": "Snacks & Confectionery",
                "default_unit": UnitEnum.PACKET.value,
                "sp": Decimal("80.00"),
                "cost": Decimal("68.00"),
                "barcode": "8901719101014",
                "discount_value": Decimal("0.00"),
                "discount_type": "percentage",
                "cashback_value": Decimal("0.00"),
                "cashback_type": "percentage",
                "min_stock": Decimal("15.000"),
                "batches": [
                    {
                        "num": "PARLE-GOLD-01",
                        "qty": Decimal("40.000"),
                        "init": Decimal("45.000"),
                        "expiry": today + timedelta(days=220),
                        "cost": Decimal("68.00"),
                        "purchase": today - timedelta(days=12),
                    },
                ],
            },
            # 4. Beverages
            {
                "name": "Tata Tea Gold Leaf (500g)",
                "category": "Beverages",
                "default_unit": UnitEnum.PACKET.value,
                "sp": Decimal("305.00"),
                "cost": Decimal("255.00"),
                "barcode": "8901030381027",
                "discount_value": Decimal("10.00"),
                "discount_type": "percentage",
                "cashback_value": Decimal("0.00"),
                "cashback_type": "percentage",
                "min_stock": Decimal("8.000"),
                "batches": [
                    {
                        "num": "TATA-TEA-001",
                        "qty": Decimal("20.000"),
                        "init": Decimal("25.000"),
                        "expiry": today + timedelta(days=360),
                        "cost": Decimal("255.00"),
                        "purchase": today - timedelta(days=20),
                    },
                ],
            },
            {
                "name": "Nescafe Classic Instant Coffee Jar (100g)",
                "category": "Beverages",
                "default_unit": UnitEnum.BOTTLE.value,
                "sp": Decimal("325.00"),
                "cost": Decimal("270.00"),
                "barcode": "8901058852851",
                "discount_value": Decimal("0.00"),
                "discount_type": "percentage",
                "cashback_value": Decimal("10.00"),
                "cashback_type": "fixed",
                "min_stock": Decimal("6.000"),
                "batches": [
                    {
                        "num": "NESC-COF-01",
                        "qty": Decimal("18.000"),
                        "init": Decimal("20.000"),
                        "expiry": today + timedelta(days=480),
                        "cost": Decimal("270.00"),
                        "purchase": today - timedelta(days=16),
                    },
                ],
            },
            {
                "name": "Coca-Cola Soft Drink Can (300 ML)",
                "category": "Beverages",
                "default_unit": UnitEnum.CAN.value,
                "sp": Decimal("38.00"),
                "cost": Decimal("30.00"),
                "barcode": "8901764012211",
                "discount_value": Decimal("0.00"),
                "discount_type": "percentage",
                "cashback_value": Decimal("0.00"),
                "cashback_type": "percentage",
                "min_stock": Decimal("24.000"),
                "batches": [
                    {
                        "num": "COKE-CAN-001",
                        "qty": Decimal("48.000"),
                        "init": Decimal("50.000"),
                        "expiry": today + timedelta(days=200),
                        "cost": Decimal("30.00"),
                        "purchase": today - timedelta(days=10),
                    },
                ],
            },
            {
                "name": "Real Fruit Power Mixed Fruit Juice (1 LITER)",
                # Low stock item (3 units < threshold 10)
                "category": "Beverages",
                "default_unit": UnitEnum.PACKET.value,
                "sp": Decimal("125.00"),
                "cost": Decimal("100.00"),
                "barcode": "8901888001014",
                "discount_value": Decimal("0.00"),
                "discount_type": "percentage",
                "cashback_value": Decimal("0.00"),
                "cashback_type": "percentage",
                "min_stock": Decimal("10.000"),
                "batches": [
                    {
                        "num": "REAL-JUICE-01",
                        "qty": Decimal("3.000"),
                        "init": Decimal("20.000"),
                        "expiry": today + timedelta(days=120),
                        "cost": Decimal("100.00"),
                        "purchase": today - timedelta(days=18),
                    },
                ],
            },
            # 5. Personal Care
            {
                "name": "Dettol Original Liquid Handwash (750 ML Refill)",
                "category": "Personal Care",
                "default_unit": UnitEnum.PACKET.value,
                "sp": Decimal("125.00"),
                "cost": Decimal("98.00"),
                "barcode": "8901396388233",
                "discount_value": Decimal("10.00"),
                "discount_type": "percentage",
                "cashback_value": Decimal("0.00"),
                "cashback_type": "percentage",
                "min_stock": Decimal("10.000"),
                "batches": [
                    {
                        "num": "DETT-HW-001",
                        "qty": Decimal("22.000"),
                        "init": Decimal("25.000"),
                        "expiry": today + timedelta(days=320),
                        "cost": Decimal("98.00"),
                        "purchase": today - timedelta(days=18),
                    },
                ],
            },
            {
                "name": "Colgate Total Charcoal Deep Clean Toothpaste (120g)",
                "category": "Personal Care",
                "default_unit": UnitEnum.PIECE.value,
                "sp": Decimal("135.00"),
                "cost": Decimal("105.00"),
                "barcode": "8901314510029",
                "discount_value": Decimal("0.00"),
                "discount_type": "percentage",
                "cashback_value": Decimal("0.00"),
                "cashback_type": "percentage",
                "min_stock": Decimal("10.000"),
                "batches": [
                    {
                        "num": "COLG-TC-001",
                        "qty": Decimal("25.000"),
                        "init": Decimal("30.000"),
                        "expiry": today + timedelta(days=380),
                        "cost": Decimal("105.00"),
                        "purchase": today - timedelta(days=16),
                    },
                ],
            },
            {
                "name": "Dove Deep Moisture Body Wash (250 ML)",
                # Out-of-stock condition (qty 0) to test out-of-stock badge & cart prevention
                "category": "Personal Care",
                "default_unit": UnitEnum.BOTTLE.value,
                "sp": Decimal("199.00"),
                "cost": Decimal("155.00"),
                "barcode": "8901030733802",
                "discount_value": Decimal("0.00"),
                "discount_type": "percentage",
                "cashback_value": Decimal("5.00"),
                "cashback_type": "percentage",
                "min_stock": Decimal("6.000"),
                "batches": [
                    {
                        "num": "DOVE-BW-DEPLETED",
                        "qty": Decimal("0.000"),
                        "init": Decimal("20.000"),
                        "expiry": today + timedelta(days=290),
                        "cost": Decimal("155.00"),
                        "purchase": today - timedelta(days=80),
                    },
                ],
            },
            {
                "name": "Lifebuoy Total 10 Germ Protection Soap (4 x 125g)",
                "category": "Personal Care",
                "default_unit": UnitEnum.BOX.value,
                "sp": Decimal("140.00"),
                "cost": Decimal("112.00"),
                "barcode": "8901030722011",
                "discount_value": Decimal("10.00"),
                "discount_type": "fixed",
                "cashback_value": Decimal("0.00"),
                "cashback_type": "percentage",
                "min_stock": Decimal("12.000"),
                "batches": [
                    {
                        "num": "LIFE-SOAP-01",
                        "qty": Decimal("28.000"),
                        "init": Decimal("35.000"),
                        "expiry": today + timedelta(days=350),
                        "cost": Decimal("112.00"),
                        "purchase": today - timedelta(days=14),
                    },
                ],
            },
            # 6. Household & Cleaning
            {
                "name": "Surf Excel Matic Top Load Liquid Detergent (1 LITER)",
                "category": "Household & Cleaning",
                "default_unit": UnitEnum.BOTTLE.value,
                "sp": Decimal("199.00"),
                "cost": Decimal("160.00"),
                "barcode": "8901030895425",
                "discount_value": Decimal("15.00"),
                "discount_type": "percentage",
                "cashback_value": Decimal("0.00"),
                "cashback_type": "percentage",
                "min_stock": Decimal("10.000"),
                "batches": [
                    {
                        "num": "SURF-MAT-001",
                        "qty": Decimal("20.000"),
                        "init": Decimal("25.000"),
                        "expiry": today + timedelta(days=530),
                        "cost": Decimal("160.00"),
                        "purchase": today - timedelta(days=20),
                    },
                ],
            },
            {
                "name": "Vim Lemon Dishwash Gel (750 ML)",
                "category": "Household & Cleaning",
                "default_unit": UnitEnum.BOTTLE.value,
                "sp": Decimal("139.00"),
                "cost": Decimal("110.00"),
                "barcode": "8901030022463",
                "discount_value": Decimal("10.00"),
                "discount_type": "fixed",
                "cashback_value": Decimal("0.00"),
                "cashback_type": "percentage",
                "min_stock": Decimal("12.000"),
                "batches": [
                    {
                        "num": "VIM-GEL-001",
                        "qty": Decimal("30.000"),
                        "init": Decimal("35.000"),
                        "expiry": today + timedelta(days=420),
                        "cost": Decimal("110.00"),
                        "purchase": today - timedelta(days=15),
                    },
                ],
            },
            {
                "name": "Harpic Power Plus Disinfectant Toilet Cleaner (1 LITER)",
                "category": "Household & Cleaning",
                "default_unit": UnitEnum.BOTTLE.value,
                "sp": Decimal("195.00"),
                "cost": Decimal("155.00"),
                "barcode": "8901396112012",
                "discount_value": Decimal("5.00"),
                "discount_type": "percentage",
                "cashback_value": Decimal("0.00"),
                "cashback_type": "percentage",
                "min_stock": Decimal("10.000"),
                "batches": [
                    {
                        "num": "HARP-PLUS-01",
                        "qty": Decimal("25.000"),
                        "init": Decimal("30.000"),
                        "expiry": today + timedelta(days=360),
                        "cost": Decimal("155.00"),
                        "purchase": today - timedelta(days=12),
                    },
                ],
            },
            # 7. Spices & Condiments
            {
                "name": "Everest Masala Garam Masala (100g)",
                "category": "Spices & Condiments",
                "default_unit": UnitEnum.PACKET.value,
                "sp": Decimal("85.00"),
                "cost": Decimal("68.00"),
                "barcode": "8901786081014",
                "discount_value": Decimal("0.00"),
                "discount_type": "percentage",
                "cashback_value": Decimal("0.00"),
                "cashback_type": "percentage",
                "min_stock": Decimal("15.000"),
                "batches": [
                    {
                        "num": "EVER-GM-01",
                        "qty": Decimal("30.000"),
                        "init": Decimal("35.000"),
                        "expiry": today + timedelta(days=250),
                        "cost": Decimal("68.00"),
                        "purchase": today - timedelta(days=15),
                    },
                ],
            },
            {
                "name": "Catch Black Pepper Sprinkler (100g)",
                "category": "Spices & Condiments",
                "default_unit": UnitEnum.BOTTLE.value,
                "sp": Decimal("99.00"),
                "cost": Decimal("80.00"),
                "barcode": "8901192101018",
                "discount_value": Decimal("0.00"),
                "discount_type": "percentage",
                "cashback_value": Decimal("0.00"),
                "cashback_type": "percentage",
                "min_stock": Decimal("10.000"),
                "batches": [
                    {
                        "num": "CATCH-PEP-01",
                        "qty": Decimal("25.000"),
                        "init": Decimal("30.000"),
                        "expiry": today + timedelta(days=300),
                        "cost": Decimal("80.00"),
                        "purchase": today - timedelta(days=10),
                    },
                ],
            },
        ]

        flagship_prod_map: dict[str, Product] = {}
        for pdata in flagship_products_def:
            prod = Product(
                product_id=uuid.uuid4(),
                store_id=flagship.store_id,
                name=pdata["name"],
                category=pdata["category"],
                default_unit=pdata["default_unit"],
                selling_price=pdata["sp"],
                cost_price=pdata["cost"],
                barcode=pdata["barcode"],
                discount_value=pdata["discount_value"],
                discount_type=pdata["discount_type"],
                cashback_value=pdata["cashback_value"],
                cashback_type=pdata["cashback_type"],
                min_stock_alert_threshold=pdata["min_stock"],
                is_active=True,
            )
            db.add(prod)
            db.flush()
            flagship_prod_map[pdata["name"]] = prod

            for bdata in pdata["batches"]:
                batch = Batch(
                    batch_id=uuid.uuid4(),
                    store_id=flagship.store_id,
                    product_id=prod.product_id,
                    batch_identifier=bdata["num"],
                    initial_quantity=bdata["init"],
                    current_quantity=bdata["qty"],
                    purchase_price=bdata["cost"],
                    expiry_date=bdata["expiry"],
                    purchase_date=bdata["purchase"],
                )
                db.add(batch)

        # Products in S-Mart store
        smart_prods_def = [
            {
                "name": "Daawat Rozana Super Basmati Rice (5 KG)",
                "category": "Grocery & Staples",
                "default_unit": UnitEnum.KG.value,
                "sp": Decimal("399.00"),
                "cost": Decimal("320.00"),
                "barcode": "8901537001052",
                "discount_value": Decimal("10.00"),
                "discount_type": "percentage",
                "min_stock": Decimal("15.000"),
                "batches": [
                    {
                        "num": "SMART-RICE-01",
                        "qty": Decimal("20.000"),
                        "init": Decimal("20.000"),
                        "expiry": today + timedelta(days=280),
                        "cost": Decimal("320.00"),
                        "purchase": today - timedelta(days=35),
                    }
                ],
            },
            {
                "name": "Fortune Sunlite Refined Sunflower Oil (1 LITER)",
                "category": "Grocery & Staples",
                "default_unit": UnitEnum.BOTTLE.value,
                "sp": Decimal("148.00"),
                "cost": Decimal("125.00"),
                "barcode": "8906007281234",
                "discount_value": Decimal("10.00"),
                "discount_type": "fixed",
                "min_stock": Decimal("10.000"),
                "batches": [
                    {
                        "num": "SMART-OIL-01",
                        "qty": Decimal("15.000"),
                        "init": Decimal("15.000"),
                        "expiry": today + timedelta(days=230),
                        "cost": Decimal("125.00"),
                        "purchase": today - timedelta(days=30),
                    }
                ],
            },
            {
                "name": "Tata Tea Gold Leaf (500g)",
                "category": "Beverages",
                "default_unit": UnitEnum.PACKET.value,
                "sp": Decimal("305.00"),
                "cost": Decimal("255.00"),
                "barcode": "8901030381027",
                "discount_value": Decimal("10.00"),
                "discount_type": "percentage",
                "min_stock": Decimal("8.000"),
                "batches": [
                    {
                        "num": "SMART-TEA-01",
                        "qty": Decimal("25.000"),
                        "init": Decimal("25.000"),
                        "expiry": today + timedelta(days=360),
                        "cost": Decimal("255.00"),
                        "purchase": today - timedelta(days=20),
                    }
                ],
            },
            {
                "name": "Haldiram's Nagpur Bhujia Sev (400g)",
                "category": "Snacks & Confectionery",
                "default_unit": UnitEnum.PACKET.value,
                "sp": Decimal("99.00"),
                "cost": Decimal("80.00"),
                "barcode": "8904063200054",
                "discount_value": Decimal("10.00"),
                "discount_type": "percentage",
                "min_stock": Decimal("12.000"),
                "batches": [
                    {
                        "num": "SMART-BHUJ-01",
                        "qty": Decimal("30.000"),
                        "init": Decimal("30.000"),
                        "expiry": today + timedelta(days=180),
                        "cost": Decimal("80.00"),
                        "purchase": today - timedelta(days=14),
                    }
                ],
            },
            {
                # Unique branch product (tests inter-store auto product creation!)
                "name": "Kissan Fresh Tomato Ketchup (950g)",
                "category": "Grocery & Staples",
                "default_unit": UnitEnum.BOTTLE.value,
                "sp": Decimal("130.00"),
                "cost": Decimal("100.00"),
                "barcode": "8901030387555",
                "discount_value": Decimal("0.00"),
                "discount_type": "percentage",
                "min_stock": Decimal("10.000"),
                "batches": [
                    {
                        "num": "SMART-KISSAN-01",
                        "qty": Decimal("20.000"),
                        "init": Decimal("20.000"),
                        "expiry": today + timedelta(days=300),
                        "cost": Decimal("100.00"),
                        "purchase": today - timedelta(days=25),
                    }
                ],
            },
            {
                # Unique branch product
                "name": "Maggi 2-Minute Masala Noodles (Pack of 12)",
                "category": "Snacks & Confectionery",
                "default_unit": UnitEnum.PACKET.value,
                "sp": Decimal("168.00"),
                "cost": Decimal("140.00"),
                "barcode": "8901058861112",
                "discount_value": Decimal("8.00"),
                "discount_type": "percentage",
                "min_stock": Decimal("10.000"),
                "batches": [
                    {
                        "num": "SMART-MAGGI-01",
                        "qty": Decimal("25.000"),
                        "init": Decimal("30.000"),
                        "expiry": today + timedelta(days=240),
                        "cost": Decimal("140.00"),
                        "purchase": today - timedelta(days=15),
                    }
                ],
            },
        ]

        smart_prod_map: dict[str, Product] = {}
        for pdata in smart_prods_def:
            prod = Product(
                product_id=uuid.uuid4(),
                store_id=smart.store_id,
                name=pdata["name"],
                category=pdata["category"],
                default_unit=pdata["default_unit"],
                selling_price=pdata["sp"],
                cost_price=pdata["cost"],
                barcode=pdata["barcode"],
                discount_value=pdata["discount_value"],
                discount_type=pdata["discount_type"],
                min_stock_alert_threshold=pdata["min_stock"],
                is_active=True,
            )
            db.add(prod)
            db.flush()
            smart_prod_map[pdata["name"]] = prod

            for bdata in pdata["batches"]:
                batch = Batch(
                    batch_id=uuid.uuid4(),
                    store_id=smart.store_id,
                    product_id=prod.product_id,
                    batch_identifier=bdata["num"],
                    initial_quantity=bdata["init"],
                    current_quantity=bdata["qty"],
                    purchase_price=bdata["cost"],
                    expiry_date=bdata["expiry"],
                    purchase_date=bdata["purchase"],
                )
                db.add(batch)

        db.commit()

        print("[8/10] Setting up Inter-Store Stock Transfers...")
        # Transfer 1: Outward from Flagship -> S-Mart (COMPLETED)
        trf1 = StockTransfer(
            transfer_id=uuid.uuid4(),
            transfer_number="TRF-00001",
            source_store_id=flagship.store_id,
            destination_store_id=smart.store_id,
            created_by_user_id=admin_user.user_id,
            transferred_by_name="Akash Bag",
            status="COMPLETED",
            notes="Initial stock transfer for S-Mart branch inventory setup",
            total_items=3,
            total_quantity=Decimal("18.000"),
            created_at=datetime.now(timezone.utc) - timedelta(days=6),
        )
        db.add(trf1)
        db.flush()

        items_to_add_trf1 = [
            ("Daawat Rozana Super Basmati Rice (5 KG)", Decimal("5.000"), UnitEnum.KG.value, "Grocery & Staples"),
            ("Fortune Sunlite Refined Sunflower Oil (1 LITER)", Decimal("3.000"), UnitEnum.BOTTLE.value, "Grocery & Staples"),
            ("Tata Salt Vacuum Evaporated (1 KG)", Decimal("10.000"), UnitEnum.PACKET.value, "Grocery & Staples"),
        ]
        for pname, qty, unit, cat in items_to_add_trf1:
            sprod = flagship_prod_map.get(pname)
            dprod = smart_prod_map.get(pname)
            db.add(
                StockTransferItem(
                    item_id=uuid.uuid4(),
                    transfer_id=trf1.transfer_id,
                    source_product_id=sprod.product_id if sprod else None,
                    destination_product_id=dprod.product_id if dprod else None,
                    product_name=pname,
                    category=cat,
                    unit=unit,
                    quantity=qty,
                    auto_created_product=False,
                )
            )

        # Transfer 2: Inward from S-Mart -> Flagship (COMPLETED)
        trf2 = StockTransfer(
            transfer_id=uuid.uuid4(),
            transfer_number="TRF-00002",
            source_store_id=smart.store_id,
            destination_store_id=flagship.store_id,
            created_by_user_id=admin_user.user_id,
            transferred_by_name="Akash Bag",
            status="COMPLETED",
            notes="Weekend stock rebalancing back to Flagship",
            total_items=2,
            total_quantity=Decimal("10.000"),
            created_at=datetime.now(timezone.utc) - timedelta(days=2),
        )
        db.add(trf2)
        db.flush()

        items_to_add_trf2 = [
            ("Tata Tea Gold Leaf (500g)", Decimal("5.000"), UnitEnum.PACKET.value, "Beverages"),
            ("Haldiram's Nagpur Bhujia Sev (400g)", Decimal("5.000"), UnitEnum.PACKET.value, "Snacks & Confectionery"),
        ]
        for pname, qty, unit, cat in items_to_add_trf2:
            sprod = smart_prod_map.get(pname)
            dprod = flagship_prod_map.get(pname)
            db.add(
                StockTransferItem(
                    item_id=uuid.uuid4(),
                    transfer_id=trf2.transfer_id,
                    source_product_id=sprod.product_id if sprod else None,
                    destination_product_id=dprod.product_id if dprod else None,
                    product_name=pname,
                    category=cat,
                    unit=unit,
                    quantity=qty,
                    auto_created_product=False,
                )
            )

        # Transfer 3: Outward from Flagship -> S-Mart (COMPLETED)
        trf3 = StockTransfer(
            transfer_id=uuid.uuid4(),
            transfer_number="TRF-00003",
            source_store_id=flagship.store_id,
            destination_store_id=smart.store_id,
            created_by_user_id=admin_user.user_id,
            transferred_by_name="Akash Bag",
            status="COMPLETED",
            notes="Mid-week replenishment dispatch",
            total_items=2,
            total_quantity=Decimal("12.000"),
            created_at=datetime.now(timezone.utc) - timedelta(hours=4),
        )
        db.add(trf3)
        db.flush()

        items_to_add_trf3 = [
            ("Aashirvaad Shudh Chakki Atta (10 KG)", Decimal("8.000"), UnitEnum.PACKET.value, "Grocery & Staples"),
            ("Surf Excel Matic Top Load Liquid Detergent (1 LITER)", Decimal("4.000"), UnitEnum.BOTTLE.value, "Household & Cleaning"),
        ]
        for pname, qty, unit, cat in items_to_add_trf3:
            sprod = flagship_prod_map.get(pname)
            dprod = smart_prod_map.get(pname)
            db.add(
                StockTransferItem(
                    item_id=uuid.uuid4(),
                    transfer_id=trf3.transfer_id,
                    source_product_id=sprod.product_id if sprod else None,
                    destination_product_id=dprod.product_id if dprod else None,
                    product_name=pname,
                    category=cat,
                    unit=unit,
                    quantity=qty,
                    auto_created_product=False,
                )
            )

        db.commit()

        print("[9/10] Setting up Transactions, POS Billing & Invoices...")
        # Helper to persist a transaction with batch allocation
        def persist_tx(store_obj, cashier_obj, tx_data, prod_map):
            cust_obj = customer_map.get(tx_data["customer_name"]) if tx_data["customer_name"] else None
            tx_date = datetime.now(timezone.utc) - timedelta(
                days=tx_data["days_ago"],
                hours=tx_data.get("hours_ago", 2),
            )

            subtotal = Decimal("0.00")
            item_disc_total = Decimal("0.00")
            items_to_persist: list[TransactionItem] = []
            allocations_to_persist: list[TransactionBatchAllocation] = []

            for prod_name, qty, unit_price, disc_pct in tx_data["items"]:
                prod = prod_map[prod_name]
                base_line = (qty * unit_price).quantize(Decimal("0.01"))
                disc_amount = (base_line * (disc_pct / Decimal("100"))).quantize(Decimal("0.01"))
                line_total = base_line - disc_amount

                subtotal += base_line
                item_disc_total += disc_amount

                t_item = TransactionItem(
                    item_id=uuid.uuid4(),
                    product_id=prod.product_id,
                    product_name=prod.name,
                    category=prod.category,
                    unit=prod.default_unit,
                    quantity=qty,
                    unit_price=unit_price,
                    item_discount_pct=disc_pct,
                    category_discount_pct=Decimal("0.00"),
                    cashback_amount=Decimal("0.00"),
                    cashback_pct=Decimal("0.00"),
                    discount_amount=disc_amount,
                    discount_pct=disc_pct,
                    line_base_total=base_line,
                    line_discount_amount=disc_amount,
                    line_total=line_total,
                )
                items_to_persist.append(t_item)

                # FEFO batch allocation
                target_batch = (
                    db.query(Batch)
                    .filter(Batch.product_id == prod.product_id, Batch.store_id == store_obj.store_id)
                    .order_by(Batch.expiry_date.asc())
                    .first()
                )
                if target_batch:
                    alloc = TransactionBatchAllocation(
                        allocation_id=uuid.uuid4(),
                        transaction_item_id=t_item.item_id,
                        batch_id=target_batch.batch_id,
                        product_id=prod.product_id,
                        quantity_deducted=qty,
                        batch_identifier=target_batch.batch_identifier,
                        expiry_date=target_batch.expiry_date,
                    )
                    allocations_to_persist.append(alloc)

            final_total = subtotal - item_disc_total
            rec_amt = tx_data["received"] if tx_data["received"] > 0 else (
                Decimal("0.00") if tx_data["method"] == PaymentMethod.CREDIT.value else final_total
            )

            tx = Transaction(
                transaction_id=uuid.uuid4(),
                store_id=store_obj.store_id,
                invoice_seq=tx_data["seq"],
                invoice_number=tx_data["inv"],
                cashier_id=cashier_obj.user_id,
                customer_id=cust_obj.customer_id if cust_obj else None,
                customer_name=cust_obj.name if cust_obj else "Walk-in Customer",
                customer_phone=cust_obj.phone if cust_obj else None,
                customer_email=cust_obj.email if cust_obj else None,
                subtotal=subtotal,
                item_discount_amount=item_disc_total,
                category_discount_amount=Decimal("0.00"),
                total_discount_percentage=Decimal("0.00"),
                total_discount_amount=item_disc_total,
                total_cashback_amount=Decimal("0.00"),
                tax_amount=Decimal("0.00"),
                final_total=final_total,
                received_amount=rec_amt,
                balance_amount=tx_data["balance"],
                payment_method=tx_data["method"],
                payment_status=tx_data["status"],
                notes=tx_data.get("notes", "Counter POS Sale"),
                offline_synced=False,
                created_at=tx_date,
            )
            db.add(tx)
            db.flush()

            for item in items_to_persist:
                item.transaction_id = tx.transaction_id
                db.add(item)
            db.flush()

            for alloc in allocations_to_persist:
                db.add(alloc)

        # Flagship Store Invoices (INV-00001 to INV-00011 across 25 days to Today)
        flagship_txs = [
            {
                "seq": 1,
                "inv": "INV-00001",
                "days_ago": 25,
                "customer_name": "Rahul Sharma",
                "method": PaymentMethod.UPI.value,
                "status": PaymentStatus.PAID.value,
                "received": Decimal("973.00"),
                "balance": Decimal("0.00"),
                "items": [
                    ("Daawat Rozana Super Basmati Rice (5 KG)", Decimal("2.000"), Decimal("399.00"), Decimal("10.00")),
                    ("Fortune Sunlite Refined Sunflower Oil (1 LITER)", Decimal("1.000"), Decimal("148.00"), Decimal("0.00")),
                    ("Tata Salt Vacuum Evaporated (1 KG)", Decimal("1.000"), Decimal("25.00"), Decimal("0.00")),
                ],
                "notes": "Monthly grocery basket via UPI",
            },
            {
                "seq": 2,
                "inv": "INV-00002",
                "days_ago": 18,
                "customer_name": "Priya Patel",
                "method": PaymentMethod.CASH.value,
                "status": PaymentStatus.PAID.value,
                "received": Decimal("600.00"),
                "balance": Decimal("90.00"),
                "items": [
                    ("Amul Salted Butter (500g)", Decimal("1.000"), Decimal("260.00"), Decimal("0.00")),
                    ("Mother Dairy Classic Paneer (200g)", Decimal("2.000"), Decimal("90.00"), Decimal("0.00")),
                    ("Britannia Good Day Butter Cookies (200g)", Decimal("2.000"), Decimal("35.00"), Decimal("0.00")),
                ],
                "notes": "Cash checkout with change returned ₹90.00",
            },
            {
                "seq": 3,
                "inv": "INV-00003",
                "days_ago": 14,
                "customer_name": "Amit Ghosh",
                "method": PaymentMethod.CARD.value,
                "status": PaymentStatus.PAID.value,
                "received": Decimal("1652.00"),
                "balance": Decimal("0.00"),
                "items": [
                    ("Aashirvaad Shudh Chakki Atta (10 KG)", Decimal("2.000"), Decimal("435.00"), Decimal("5.00")),
                    ("Daawat Rozana Super Basmati Rice (5 KG)", Decimal("1.000"), Decimal("399.00"), Decimal("10.00")),
                    ("Fortune Sunlite Refined Sunflower Oil (1 LITER)", Decimal("2.000"), Decimal("148.00"), Decimal("0.00")),
                    ("Tata Tea Gold Leaf (500g)", Decimal("1.000"), Decimal("305.00"), Decimal("10.00")),
                ],
                "notes": "Bulk supplies order paid via Debit Card",
            },
            {
                "seq": 4,
                "inv": "INV-00004",
                "days_ago": 10,
                "customer_name": "Akash Bag",
                "method": PaymentMethod.UPI.value,
                "status": PaymentStatus.PAID.value,
                "received": Decimal("353.00"),
                "balance": Decimal("0.00"),
                "items": [
                    ("Amul Taaza Fresh Toned Milk (1 LITER)", Decimal("2.000"), Decimal("54.00"), Decimal("0.00")),
                    ("Cadbury Dairy Milk Silk Chocolate (150g)", Decimal("1.000"), Decimal("160.00"), Decimal("10.00")),
                    ("Haldiram's Nagpur Bhujia Sev (400g)", Decimal("1.000"), Decimal("99.00"), Decimal("0.00")),
                ],
                "notes": "Personal household items via Google Pay",
            },
            {
                "seq": 5,
                "inv": "INV-00005",
                "days_ago": 7,
                "customer_name": "Sunita Devi",
                "method": PaymentMethod.CASH.value,
                "status": PaymentStatus.PAID.value,
                "received": Decimal("400.00"),
                "balance": Decimal("1.00"),
                "items": [
                    ("Vim Lemon Dishwash Gel (750 ML)", Decimal("1.000"), Decimal("139.00"), Decimal("0.00")),
                    ("Dettol Original Liquid Handwash (750 ML Refill)", Decimal("1.000"), Decimal("125.00"), Decimal("0.00")),
                    ("Colgate Total Charcoal Deep Clean Toothpaste (120g)", Decimal("1.000"), Decimal("135.00"), Decimal("0.00")),
                ],
                "notes": "Cash on counter with ₹1 change",
            },
            {
                "seq": 6,
                "inv": "INV-00006",
                "days_ago": 4,
                "customer_name": "Priya Patel",
                "method": PaymentMethod.UPI.value,
                "status": PaymentStatus.PAID.value,
                "received": Decimal("680.00"),
                "balance": Decimal("0.00"),
                "items": [
                    ("Amul Salted Butter (500g)", Decimal("2.000"), Decimal("260.00"), Decimal("0.00")),
                    ("Mother Dairy Classic Paneer (200g)", Decimal("1.000"), Decimal("90.00"), Decimal("0.00")),
                    ("Everest Masala Garam Masala (100g)", Decimal("1.000"), Decimal("85.00"), Decimal("0.00")),
                ],
                "notes": "Weekend cooking essentials via PhonePe",
            },
            {
                "seq": 7,
                "inv": "INV-00007",
                "days_ago": 2,
                "customer_name": "Amit Ghosh",
                "method": PaymentMethod.CARD.value,
                "status": PaymentStatus.PAID.value,
                "received": Decimal("1250.00"),
                "balance": Decimal("0.00"),
                "items": [
                    ("Engine Pure Mustard Oil (1 LITER)", Decimal("2.000"), Decimal("165.00"), Decimal("0.00")),
                    ("Aashirvaad Shudh Chakki Atta (10 KG)", Decimal("1.000"), Decimal("435.00"), Decimal("5.00")),
                    ("Tata Tea Gold Leaf (500g)", Decimal("1.000"), Decimal("305.00"), Decimal("10.00")),
                    ("Dhampure Pure White Refined Sugar (1 KG)", Decimal("2.000"), Decimal("48.00"), Decimal("0.00")),
                ],
                "notes": "Catering order via POS Credit Card machine",
            },
            {
                "seq": 8,
                "inv": "INV-00008",
                "days_ago": 1,
                "customer_name": "Vikram Malhotra",
                "method": PaymentMethod.CREDIT.value,
                "status": PaymentStatus.PENDING.value,  # Tests Khata / Credit Account pending balance!
                "received": Decimal("0.00"),
                "balance": Decimal("0.00"),
                "items": [
                    ("Surf Excel Matic Top Load Liquid Detergent (1 LITER)", Decimal("1.000"), Decimal("199.00"), Decimal("15.00")),
                    ("Tata Tea Gold Leaf (500g)", Decimal("1.000"), Decimal("305.00"), Decimal("10.00")),
                    ("Amul Salted Butter (500g)", Decimal("1.000"), Decimal("260.00"), Decimal("0.00")),
                ],
                "notes": "Khata Credit bill - To be settled on month-end",
            },
            {
                "seq": 9,
                "inv": "INV-00009",
                "days_ago": 0,
                "hours_ago": 8,
                "customer_name": "Rahul Sharma",
                "method": PaymentMethod.UPI.value,
                "status": PaymentStatus.PAID.value,
                "received": Decimal("260.00"),
                "balance": Decimal("0.00"),
                "items": [
                    ("Coca-Cola Soft Drink Can (300 ML)", Decimal("2.000"), Decimal("38.00"), Decimal("0.00")),
                    ("Lay's India's Magic Masala Chips (50g)", Decimal("2.000"), Decimal("20.00"), Decimal("0.00")),
                    ("Cadbury Dairy Milk Silk Chocolate (150g)", Decimal("1.000"), Decimal("160.00"), Decimal("10.00")),
                ],
                "notes": "Morning snacks checkout via UPI QR",
            },
            {
                "seq": 10,
                "inv": "INV-00010",
                "days_ago": 0,
                "hours_ago": 4,
                "customer_name": None,  # Walk-in customer test case
                "method": PaymentMethod.CASH.value,
                "status": PaymentStatus.PAID.value,
                "received": Decimal("100.00"),
                "balance": Decimal("27.00"),
                "items": [
                    ("Britannia Good Day Butter Cookies (200g)", Decimal("1.000"), Decimal("35.00"), Decimal("0.00")),
                    ("Coca-Cola Soft Drink Can (300 ML)", Decimal("1.000"), Decimal("38.00"), Decimal("0.00")),
                ],
                "notes": "Quick counter sale for walk-in customer",
            },
            {
                "seq": 11,
                "inv": "INV-00011",
                "days_ago": 0,
                "hours_ago": 1,
                "customer_name": "Ananya Sen",
                "method": PaymentMethod.CARD.value,
                "status": PaymentStatus.PAID.value,
                "received": Decimal("450.00"),
                "balance": Decimal("0.00"),
                "items": [
                    ("Harpic Power Plus Disinfectant Toilet Cleaner (1 LITER)", Decimal("1.000"), Decimal("195.00"), Decimal("5.00")),
                    ("Dettol Original Liquid Handwash (750 ML Refill)", Decimal("1.000"), Decimal("125.00"), Decimal("10.00")),
                    ("Lifebuoy Total 10 Germ Protection Soap (4 x 125g)", Decimal("1.000"), Decimal("140.00"), Decimal("0.00")),
                ],
                "notes": "Evening hygiene supplies via Contactless Card",
            },
        ]

        for tx_data in flagship_txs:
            persist_tx(flagship, clerk_user, tx_data, flagship_prod_map)

        # S-Mart Store Invoices (INV-00001 to INV-00003)
        smart_txs = [
            {
                "seq": 1,
                "inv": "INV-00001",
                "days_ago": 5,
                "customer_name": "Rajesh Gupta",
                "method": PaymentMethod.UPI.value,
                "status": PaymentStatus.PAID.value,
                "received": Decimal("498.00"),
                "balance": Decimal("0.00"),
                "items": [
                    ("Maggi 2-Minute Masala Noodles (Pack of 12)", Decimal("1.000"), Decimal("168.00"), Decimal("0.00")),
                    ("Kissan Fresh Tomato Ketchup (950g)", Decimal("1.000"), Decimal("130.00"), Decimal("0.00")),
                    ("Fortune Sunlite Refined Sunflower Oil (1 LITER)", Decimal("1.000"), Decimal("148.00"), Decimal("0.00")),
                ],
                "notes": "Branch opening day sale via UPI",
            },
            {
                "seq": 2,
                "inv": "INV-00002",
                "days_ago": 2,
                "customer_name": "Rahul Sharma",
                "method": PaymentMethod.CASH.value,
                "status": PaymentStatus.PAID.value,
                "received": Decimal("500.00"),
                "balance": Decimal("101.00"),
                "items": [
                    ("Daawat Rozana Super Basmati Rice (5 KG)", Decimal("1.000"), Decimal("399.00"), Decimal("0.00")),
                ],
                "notes": "Multi-store customer shopping at New Town branch",
            },
            {
                "seq": 3,
                "inv": "INV-00003",
                "days_ago": 0,
                "hours_ago": 3,
                "customer_name": "Rajesh Gupta",
                "method": PaymentMethod.UPI.value,
                "status": PaymentStatus.PAID.value,
                "received": Decimal("298.00"),
                "balance": Decimal("0.00"),
                "items": [
                    ("Tata Tea Gold Leaf (500g)", Decimal("1.000"), Decimal("305.00"), Decimal("10.00")),
                ],
                "notes": "Evening tea refill via UPI",
            },
        ]

        for tx_data in smart_txs:
            persist_tx(smart, cashier_user, tx_data, smart_prod_map)

        db.commit()

        print("[10/10] Setting up Notification Logs & Reference States...")
        # 1. System Alerts & Notifications
        notifs_data = [
            (
                NotificationEvent.EXPIRY_WARNING.value,
                "Batch Expiring Soon Alert",
                "Batch 'AMUL-MILK-EXP-SOON' for product 'Amul Taaza Fresh Toned Milk' expires in 4 days (FEFO priority alert).",
            ),
            (
                NotificationEvent.LOW_STOCK_ALERT.value,
                "Low Stock Alert",
                "Product 'Tata Sampann Unpolished Toor Dal' has reached low stock threshold (4 units remaining).",
            ),
            (
                NotificationEvent.LOW_STOCK_ALERT.value,
                "Low Stock Alert",
                "Product 'Real Fruit Power Mixed Fruit Juice' has reached low stock threshold (3 units remaining).",
            ),
            (
                NotificationEvent.PAYMENT_CONFIRMATION.value,
                "Invoice Payment Received",
                "Tax Invoice INV-00009 for ₹260.00 successfully processed via UPI for Rahul Sharma.",
            ),
            (
                NotificationEvent.PAYMENT_CONFIRMATION.value,
                "Credit Invoice Issued (Pending Settlement)",
                "Tax Invoice INV-00008 for ₹724.00 issued on credit for Vikram Malhotra.",
            ),
        ]
        for event_type, title, msg in notifs_data:
            db.add(
                NotificationLog(
                    notification_id=uuid.uuid4(),
                    store_id=flagship.store_id,
                    event_type=event_type,
                    channel=NotificationChannel.IN_APP.value,
                    recipient=admin_email,
                    title=title,
                    message=msg,
                    status="SENT",
                    created_at=datetime.now(timezone.utc) - timedelta(hours=3),
                )
            )

        # 2. Indian States reference table
        states_count = db.query(IndianState).count()
        if states_count == 0:
            seed_file = os.path.join(os.path.dirname(__file__), "indian_states.json")
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

        print("\n=======================================================")
        print(" [SUCCESS] Local Database Successfully Cleaned & Seeded!")
        print("=======================================================")
        print(f" Stores Configured       : 3 (Flagship, S-Mart, Central)")
        print(f" Users Configured        : 5 (Super Admin, Mgr, Clerk, Cashier)")
        print(f" Customer Profiles       : 9 (VIP, Regular, Khata Credit, New)")
        print(f" Products Catalog        : {len(flagship_products_def) + len(smart_prods_def)} items (7 categories, 9 units)")
        print(f" POS Transactions Seeded : {len(flagship_txs) + len(smart_txs)} invoices (UPI, Cash, Card, Credit)")
        print(f" Stock Transfers         : 3 (Outward, Inward)")
        print(f" Notification Logs       : {len(notifs_data)} alerts")
        print("=======================================================\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clean and seed Save Shop local database.")
    parser.add_argument(
        "--no-clean",
        action="store_true",
        help="Do not clean up the database before seeding (append/upsert mode).",
    )
    args = parser.parse_args()

    should_clean = not args.no_clean
    seed_database(clean=should_clean)
