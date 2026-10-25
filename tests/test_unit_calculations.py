import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.exceptions import ValidationException
from app.models.inventory import UnitEnum
from app.utils.unit_calc import (
    UnitCalculator,
    quantize_currency,
    quantize_quantity,
)

# =============================================================================
# 1. DIRECT UNIT CALCULATOR TESTS: ALL UNITS & CONVERSIONS
# =============================================================================


def test_unit_normalization():
    assert UnitCalculator.normalize_unit("kg") == UnitEnum.KG
    assert UnitCalculator.normalize_unit("KGS") == UnitEnum.KG
    assert UnitCalculator.normalize_unit("kilogram") == UnitEnum.KG
    assert UnitCalculator.normalize_unit("kilograms") == UnitEnum.KG
    assert UnitCalculator.normalize_unit("gm") == UnitEnum.GRAM
    assert UnitCalculator.normalize_unit("grams") == UnitEnum.GRAM
    assert UnitCalculator.normalize_unit("dozen") == UnitEnum.DOZEN
    assert UnitCalculator.normalize_unit("doz") == UnitEnum.DOZEN
    assert UnitCalculator.normalize_unit("pieces") == UnitEnum.PIECE
    assert UnitCalculator.normalize_unit("pcs") == UnitEnum.PIECE
    assert UnitCalculator.normalize_unit("boxes") == UnitEnum.BOX
    assert UnitCalculator.normalize_unit("liter") == UnitEnum.LITER
    assert UnitCalculator.normalize_unit("litres") == UnitEnum.LITER
    assert UnitCalculator.normalize_unit("ml") == UnitEnum.ML
    assert UnitCalculator.normalize_unit("meters") == UnitEnum.METER
    assert UnitCalculator.normalize_unit("m") == UnitEnum.METER
    assert UnitCalculator.normalize_unit("bottles") == UnitEnum.BOTTLE
    assert UnitCalculator.normalize_unit("packets") == UnitEnum.PACKET
    assert UnitCalculator.normalize_unit("cans") == UnitEnum.CAN

    with pytest.raises(ValidationException):
        UnitCalculator.normalize_unit("LIGHTYEARS")

    with pytest.raises(ValidationException):
        UnitCalculator.normalize_unit(12345)


def test_unit_compatibility_matrix():
    # Weight
    assert UnitCalculator.is_compatible(UnitEnum.KG, UnitEnum.GRAM) is True
    assert UnitCalculator.is_compatible(UnitEnum.GRAM, UnitEnum.KG) is True
    assert UnitCalculator.is_compatible(UnitEnum.KG, UnitEnum.KG) is True

    # Volume
    assert UnitCalculator.is_compatible(UnitEnum.LITER, UnitEnum.ML) is True
    assert UnitCalculator.is_compatible(UnitEnum.ML, UnitEnum.LITER) is True

    # Count
    assert UnitCalculator.is_compatible(UnitEnum.DOZEN, UnitEnum.PIECE) is True
    assert UnitCalculator.is_compatible(UnitEnum.PIECE, UnitEnum.DOZEN) is True

    # Packaging to Count
    assert UnitCalculator.is_compatible(UnitEnum.BOX, UnitEnum.PIECE) is True
    assert UnitCalculator.is_compatible(UnitEnum.PIECE, UnitEnum.BOX) is True
    assert UnitCalculator.is_compatible(UnitEnum.BOX, UnitEnum.PACKET) is True

    # Length
    assert UnitCalculator.is_compatible(UnitEnum.METER, UnitEnum.METER) is True

    # Incompatible combinations across physical dimensions
    assert UnitCalculator.is_compatible(UnitEnum.KG, UnitEnum.LITER) is False
    assert UnitCalculator.is_compatible(UnitEnum.KG, UnitEnum.DOZEN) is False
    assert UnitCalculator.is_compatible(UnitEnum.GRAM, UnitEnum.BOX) is False
    assert UnitCalculator.is_compatible(UnitEnum.LITER, UnitEnum.METER) is False
    assert UnitCalculator.is_compatible(UnitEnum.DOZEN, UnitEnum.METER) is False
    assert UnitCalculator.is_compatible(UnitEnum.METER, UnitEnum.KG) is False
    assert UnitCalculator.is_compatible("UNKNOWN_A", "UNKNOWN_B") is False


def test_weight_conversions_kg_and_gram():
    # KG to GRAM
    assert UnitCalculator.convert_quantity(Decimal("1.000"), UnitEnum.KG, UnitEnum.GRAM) == Decimal("1000.000")
    assert UnitCalculator.convert_quantity(Decimal("0.250"), UnitEnum.KG, UnitEnum.GRAM) == Decimal("250.000")
    assert UnitCalculator.convert_quantity(Decimal("0.500"), UnitEnum.KG, UnitEnum.GRAM) == Decimal("500.000")
    assert UnitCalculator.convert_quantity(Decimal("1.750"), UnitEnum.KG, UnitEnum.GRAM) == Decimal("1750.000")
    assert UnitCalculator.convert_quantity(Decimal("0.005"), UnitEnum.KG, UnitEnum.GRAM) == Decimal("5.000")
    assert UnitCalculator.convert_quantity(Decimal("0.001"), UnitEnum.KG, UnitEnum.GRAM) == Decimal("1.000")

    # GRAM to KG
    assert UnitCalculator.convert_quantity(Decimal("1000.000"), UnitEnum.GRAM, UnitEnum.KG) == Decimal("1.000")
    assert UnitCalculator.convert_quantity(Decimal("500.000"), UnitEnum.GRAM, UnitEnum.KG) == Decimal("0.500")
    assert UnitCalculator.convert_quantity(Decimal("250.000"), UnitEnum.GRAM, UnitEnum.KG) == Decimal("0.250")
    assert UnitCalculator.convert_quantity(Decimal("100.000"), UnitEnum.GRAM, UnitEnum.KG) == Decimal("0.100")
    assert UnitCalculator.convert_quantity(Decimal("50.000"), UnitEnum.GRAM, UnitEnum.KG) == Decimal("0.050")
    assert UnitCalculator.convert_quantity(Decimal("1.000"), UnitEnum.GRAM, UnitEnum.KG) == Decimal("0.001")


def test_volume_conversions_liter_and_ml():
    # LITER to ML
    assert UnitCalculator.convert_quantity(Decimal("1.000"), UnitEnum.LITER, UnitEnum.ML) == Decimal("1000.000")
    assert UnitCalculator.convert_quantity(Decimal("0.750"), UnitEnum.LITER, UnitEnum.ML) == Decimal("750.000")
    assert UnitCalculator.convert_quantity(Decimal("0.200"), UnitEnum.LITER, UnitEnum.ML) == Decimal("200.000")
    assert UnitCalculator.convert_quantity(Decimal("2.500"), UnitEnum.LITER, UnitEnum.ML) == Decimal("2500.000")

    # ML to LITER
    assert UnitCalculator.convert_quantity(Decimal("1000.000"), UnitEnum.ML, UnitEnum.LITER) == Decimal("1.000")
    assert UnitCalculator.convert_quantity(Decimal("500.000"), UnitEnum.ML, UnitEnum.LITER) == Decimal("0.500")
    assert UnitCalculator.convert_quantity(Decimal("250.000"), UnitEnum.ML, UnitEnum.LITER) == Decimal("0.250")
    assert UnitCalculator.convert_quantity(Decimal("100.000"), UnitEnum.ML, UnitEnum.LITER) == Decimal("0.100")


def test_count_conversions_dozen_and_piece():
    # DOZEN to PIECE
    assert UnitCalculator.convert_quantity(Decimal("1.000"), UnitEnum.DOZEN, UnitEnum.PIECE) == Decimal("12.000")
    assert UnitCalculator.convert_quantity(Decimal("0.500"), UnitEnum.DOZEN, UnitEnum.PIECE) == Decimal("6.000")
    assert UnitCalculator.convert_quantity(Decimal("2.500"), UnitEnum.DOZEN, UnitEnum.PIECE) == Decimal("30.000")
    assert UnitCalculator.convert_quantity(Decimal("0.250"), UnitEnum.DOZEN, UnitEnum.PIECE) == Decimal("3.000")

    # PIECE to DOZEN
    assert UnitCalculator.convert_quantity(Decimal("12.000"), UnitEnum.PIECE, UnitEnum.DOZEN) == Decimal("1.000")
    assert UnitCalculator.convert_quantity(Decimal("6.000"), UnitEnum.PIECE, UnitEnum.DOZEN) == Decimal("0.500")
    assert UnitCalculator.convert_quantity(Decimal("18.000"), UnitEnum.PIECE, UnitEnum.DOZEN) == Decimal("1.500")
    assert UnitCalculator.convert_quantity(Decimal("3.000"), UnitEnum.PIECE, UnitEnum.DOZEN) == Decimal("0.250")


def test_box_conversions():
    # BOX of 24 pieces
    assert UnitCalculator.convert_quantity(Decimal("1.000"), UnitEnum.BOX, UnitEnum.PIECE, items_per_box=24) == Decimal("24.000")
    assert UnitCalculator.convert_quantity(Decimal("0.500"), UnitEnum.BOX, UnitEnum.PIECE, items_per_box=24) == Decimal("12.000")
    assert UnitCalculator.convert_quantity(Decimal("2.000"), UnitEnum.BOX, UnitEnum.PIECE, items_per_box=24) == Decimal("48.000")
    assert UnitCalculator.convert_quantity(Decimal("36.000"), UnitEnum.PIECE, UnitEnum.BOX, items_per_box=24) == Decimal("1.500")

    # BOX of 10 packets
    assert UnitCalculator.convert_quantity(Decimal("3.000"), UnitEnum.BOX, UnitEnum.PACKET, items_per_box=10) == Decimal("30.000")
    assert UnitCalculator.convert_quantity(Decimal("25.000"), UnitEnum.PACKET, UnitEnum.BOX, items_per_box=10) == Decimal("2.500")


def test_price_calculation_per_unit():
    # Sugar @ 80.00 / KG -> Price per GRAM should be 0.08
    price_per_gram = UnitCalculator.calculate_price_for_unit(Decimal("80.00"), UnitEnum.KG, UnitEnum.GRAM)
    assert price_per_gram == Decimal("0.08")

    # Saffron @ 2.50 / GRAM -> Price per KG should be 2500.00
    price_per_kg = UnitCalculator.calculate_price_for_unit(Decimal("2.50"), UnitEnum.GRAM, UnitEnum.KG)
    assert price_per_kg == Decimal("2500.00")

    # Eggs @ 120.00 / DOZEN -> Price per PIECE should be 10.00
    price_per_piece = UnitCalculator.calculate_price_for_unit(Decimal("120.00"), UnitEnum.DOZEN, UnitEnum.PIECE)
    assert price_per_piece == Decimal("10.00")

    # Mangoes @ 480.00 / BOX (24 pieces) -> Price per PIECE should be 20.00
    price_box_piece = UnitCalculator.calculate_price_for_unit(Decimal("480.00"), UnitEnum.BOX, UnitEnum.PIECE, items_per_box=24)
    assert price_box_piece == Decimal("20.00")

    # Milk @ 64.00 / LITER -> Price per ML should be 0.06
    price_per_ml = UnitCalculator.calculate_price_for_unit(Decimal("64.00"), UnitEnum.LITER, UnitEnum.ML)
    assert price_per_ml == Decimal("0.06")


def test_incompatible_conversion_raises():
    with pytest.raises(ValidationException) as exc_info:
        UnitCalculator.convert_quantity(Decimal("5.000"), UnitEnum.KG, UnitEnum.LITER)
    assert "Cannot convert between incompatible units" in str(exc_info.value)

    with pytest.raises(ValidationException) as exc_info:
        UnitCalculator.convert_quantity(Decimal("2.000"), UnitEnum.DOZEN, UnitEnum.METER)
    assert "Cannot convert between incompatible units" in str(exc_info.value)

    with pytest.raises(ValidationException):
        UnitCalculator.convert_quantity(Decimal("-5.000"), UnitEnum.KG, UnitEnum.GRAM)

    with pytest.raises(ValidationException):
        UnitCalculator.calculate_price_for_unit(Decimal("-10.00"), UnitEnum.KG, UnitEnum.GRAM)


def test_format_quantity_display():
    assert UnitCalculator.format_quantity_display(Decimal("1.5"), UnitEnum.KG) == "1.500 KG"
    assert UnitCalculator.format_quantity_display(Decimal("12"), UnitEnum.PIECE) == "12.000 PIECE"
    assert UnitCalculator.format_quantity_display(Decimal("0.5"), UnitEnum.DOZEN) == "0.500 DOZEN"
    assert UnitCalculator.format_quantity_display(Decimal("2"), UnitEnum.BOX) == "2.000 BOX"


def test_calculate_line_item_helper():
    # 500 grams of Sugar (Base unit: KG, price: 60.00/KG, 10% item discount)
    res = UnitCalculator.calculate_line_item(
        quantity=Decimal("500.000"),
        requested_unit=UnitEnum.GRAM,
        product_base_unit=UnitEnum.KG,
        product_selling_price=Decimal("60.00"),
        item_discount_pct=Decimal("10.00"),
    )
    assert res["requested_quantity"] == Decimal("500.000")
    assert res["deduction_quantity"] == Decimal("0.500")  # Exactly 0.500 KG to deduct from batch
    assert res["line_base_total"] == Decimal("30.00")  # 0.5 * 60 = 30.00
    assert res["item_discount_amount"] == Decimal("3.00")  # 10% of 30 = 3.00
    assert res["line_total"] == Decimal("27.00")  # 30 - 3 = 27.00


# =============================================================================
# 2. END-TO-END POS & INVENTORY TESTS WITH ALL UNITS (KG, BOX, DOZEN, ETC.)
# =============================================================================


def setup_unit_test_store(client: TestClient, admin_headers: dict):
    resp = client.post(
        "/api/v1/stores/create",
        json={"name": f"Unit Test Store {uuid.uuid4().hex[:6]}", "phone_number": "+91 9998881111"},
        headers=admin_headers,
    )
    assert resp.status_code == 201
    store_id = resp.json()["store_id"]
    headers = {**admin_headers, "X-Store-Id": store_id}
    return store_id, headers


def test_pos_selling_kg_product_in_fractional_kg(client: TestClient, admin_headers: dict):
    """
    Product tracked in KG. Customer buys 0.350 KG directly.
    """
    store_id, headers = setup_unit_test_store(client, admin_headers)
    today = date.today()

    # Create Product (Almonds, unit: KG, price: ₹800.00/KG)
    p_resp = client.post(
        "/api/v1/inventory/products",
        json={"name": "California Almonds", "category": "Dry Fruits", "default_unit": "KG", "selling_price": "800.00"},
        headers=headers,
    )
    assert p_resp.status_code == 201
    prod_id = p_resp.json()["product_id"]

    # Inward 10.000 KG
    client.post(
        "/api/v1/inventory/receive/single",
        json={
            "product_id": prod_id,
            "batch_identifier": "BATCH-ALM-01",
            "quantity": "10.000",
            "purchase_date": today.isoformat(),
            "expiry_date": (today + timedelta(days=180)).isoformat(),
        },
        headers=headers,
    )

    # Buy 0.350 KG @ 800/KG = ₹280.00
    checkout_resp = client.post(
        "/api/v1/billing/checkout",
        json={
            "items": [{"product_id": prod_id, "quantity": "0.350", "unit": "KG"}],
            "payment_method": "CASH",
        },
        headers=headers,
    )
    assert checkout_resp.status_code == 201
    tx = checkout_resp.json()
    assert float(tx["final_total"]) == 280.00
    assert tx["items"][0]["unit"] == "KG"
    assert float(tx["items"][0]["quantity"]) == 0.350
    assert float(tx["items"][0]["line_total"]) == 280.00

    # Stock check: 10.000 - 0.350 = 9.650 KG
    prod_check = client.get(f"/api/v1/inventory/products/{prod_id}", headers=headers).json()
    assert float(prod_check["total_current_stock"]) == 9.650


def test_pos_selling_kg_product_in_grams_automatic_conversion(client: TestClient, admin_headers: dict):
    """
    Product tracked in KG. Customer buys 250 GRAMS.
    System must:
    1. Automatically convert 250 GRAM to 0.250 KG for stock depletion.
    2. Correctly compute line total: 0.250 * ₹100.00 = ₹25.00.
    3. Retain GRAM on receipt line item.
    """
    store_id, headers = setup_unit_test_store(client, admin_headers)
    today = date.today()

    # Product: White Sugar, default_unit = "KG", price = 100.00/KG
    p_resp = client.post(
        "/api/v1/inventory/products",
        json={"name": "White Sugar", "category": "Groceries", "default_unit": "KG", "selling_price": "100.00"},
        headers=headers,
    )
    assert p_resp.status_code == 201
    prod_id = p_resp.json()["product_id"]

    # Inward 5.000 KG
    client.post(
        "/api/v1/inventory/receive/single",
        json={
            "product_id": prod_id,
            "batch_identifier": "BATCH-SUGAR-01",
            "quantity": "5.000",
            "purchase_date": today.isoformat(),
            "expiry_date": (today + timedelta(days=365)).isoformat(),
        },
        headers=headers,
    )

    # Buy 250 GRAMS
    checkout_resp = client.post(
        "/api/v1/billing/checkout",
        json={
            "items": [{"product_id": prod_id, "quantity": "250.000", "unit": "GRAM"}],
            "payment_method": "UPI",
        },
        headers=headers,
    )
    assert checkout_resp.status_code == 201
    tx = checkout_resp.json()
    assert float(tx["final_total"]) == 25.00
    assert tx["items"][0]["unit"] == "GRAM"
    assert float(tx["items"][0]["quantity"]) == 250.000
    assert float(tx["items"][0]["unit_price"]) == 0.10  # 100 / 1000 = 0.10 per gram

    # Allocation should show 0.250 KG deducted from batch
    allocation = tx["items"][0]["allocations"][0]
    assert float(allocation["quantity_deducted"]) == 0.250

    # Remaining stock in KG: 5.000 - 0.250 = 4.750 KG
    prod_check = client.get(f"/api/v1/inventory/products/{prod_id}", headers=headers).json()
    assert float(prod_check["total_current_stock"]) == 4.750


def test_pos_selling_dozen_product_in_fractional_and_pieces(client: TestClient, admin_headers: dict):
    """
    Product tracked in DOZEN (e.g. Farm Fresh Eggs, ₹96.00/DOZEN).
    Customer buys:
    1. 0.500 DOZEN (half dozen) -> ₹48.00
    2. 6 PIECES (using unit="PIECE") -> ₹48.00 (half dozen equivalent)
    Total stock should drop by 1.000 DOZEN total.
    """
    store_id, headers = setup_unit_test_store(client, admin_headers)
    today = date.today()

    p_resp = client.post(
        "/api/v1/inventory/products",
        json={"name": "Farm Eggs", "category": "Poultry", "default_unit": "DOZEN", "selling_price": "96.00"},
        headers=headers,
    )
    assert p_resp.status_code == 201
    prod_id = p_resp.json()["product_id"]

    # Inward 10.000 DOZEN
    client.post(
        "/api/v1/inventory/receive/single",
        json={
            "product_id": prod_id,
            "batch_identifier": "BATCH-EGGS-01",
            "quantity": "10.000",
            "purchase_date": today.isoformat(),
            "expiry_date": (today + timedelta(days=21)).isoformat(),
        },
        headers=headers,
    )

    # 1. Buy 0.500 DOZEN
    tx1_resp = client.post(
        "/api/v1/billing/checkout",
        json={"items": [{"product_id": prod_id, "quantity": "0.500", "unit": "DOZEN"}], "payment_method": "CASH"},
        headers=headers,
    )
    assert tx1_resp.status_code == 201
    assert float(tx1_resp.json()["final_total"]) == 48.00

    # 2. Buy 6 PIECES (unit="PIECE")
    tx2_resp = client.post(
        "/api/v1/billing/checkout",
        json={"items": [{"product_id": prod_id, "quantity": "6.000", "unit": "PIECE"}], "payment_method": "CASH"},
        headers=headers,
    )
    assert tx2_resp.status_code == 201
    tx2 = tx2_resp.json()
    assert float(tx2["final_total"]) == 48.00
    assert tx2["items"][0]["unit"] == "PIECE"
    assert float(tx2["items"][0]["quantity"]) == 6.000
    assert float(tx2["items"][0]["unit_price"]) == 8.00  # 96 / 12 = 8 per egg
    # Batch deduction is 0.500 DOZEN
    assert float(tx2["items"][0]["allocations"][0]["quantity_deducted"]) == 0.500

    # Remaining stock: 10.000 - 0.500 - 0.500 = 9.000 DOZEN
    prod_check = client.get(f"/api/v1/inventory/products/{prod_id}", headers=headers).json()
    assert float(prod_check["total_current_stock"]) == 9.000


def test_pos_selling_box_product_and_pieces(client: TestClient, admin_headers: dict):
    """
    Product tracked in BOX (e.g. Alphonso Mangoes Box, ₹600.00/BOX).
    Customer buys:
    1. 2 BOXES -> ₹1200.00
    2. 0.5 BOX -> ₹300.00
    """
    store_id, headers = setup_unit_test_store(client, admin_headers)
    today = date.today()

    p_resp = client.post(
        "/api/v1/inventory/products",
        json={"name": "Alphonso Mangoes", "category": "Fruits", "default_unit": "BOX", "selling_price": "600.00"},
        headers=headers,
    )
    assert p_resp.status_code == 201
    prod_id = p_resp.json()["product_id"]

    # Inward 20.000 BOX
    client.post(
        "/api/v1/inventory/receive/single",
        json={
            "product_id": prod_id,
            "batch_identifier": "BATCH-MANGO-01",
            "quantity": "20.000",
            "purchase_date": today.isoformat(),
            "expiry_date": (today + timedelta(days=15)).isoformat(),
        },
        headers=headers,
    )

    # Buy 2 BOXES
    tx1 = client.post(
        "/api/v1/billing/checkout",
        json={"items": [{"product_id": prod_id, "quantity": "2.000", "unit": "BOX"}], "payment_method": "CASH"},
        headers=headers,
    ).json()
    assert float(tx1["final_total"]) == 1200.00

    # Buy 0.5 BOX
    tx2 = client.post(
        "/api/v1/billing/checkout",
        json={"items": [{"product_id": prod_id, "quantity": "0.500", "unit": "BOX"}], "payment_method": "CASH"},
        headers=headers,
    ).json()
    assert float(tx2["final_total"]) == 300.00

    # Remaining stock: 20.000 - 2.500 = 17.500 BOX
    prod_check = client.get(f"/api/v1/inventory/products/{prod_id}", headers=headers).json()
    assert float(prod_check["total_current_stock"]) == 17.500


def test_pos_selling_liter_and_ml(client: TestClient, admin_headers: dict):
    """
    Product tracked in LITER (e.g. Cold Pressed Mustard Oil, ₹160.00/LITER).
    Customer buys 500 ML (unit="ML").
    Expected: line_total = ₹80.00, batch deduction = 0.500 LITER.
    """
    store_id, headers = setup_unit_test_store(client, admin_headers)
    today = date.today()

    p_resp = client.post(
        "/api/v1/inventory/products",
        json={"name": "Mustard Oil", "category": "Oils", "default_unit": "LITER", "selling_price": "160.00"},
        headers=headers,
    )
    prod_id = p_resp.json()["product_id"]

    client.post(
        "/api/v1/inventory/receive/single",
        json={
            "product_id": prod_id,
            "batch_identifier": "LOT-OIL-01",
            "quantity": "15.000",
            "purchase_date": today.isoformat(),
            "expiry_date": (today + timedelta(days=200)).isoformat(),
        },
        headers=headers,
    )

    # Buy 500 ML
    tx = client.post(
        "/api/v1/billing/checkout",
        json={"items": [{"product_id": prod_id, "quantity": "500.000", "unit": "ML"}], "payment_method": "CASH"},
        headers=headers,
    ).json()
    assert float(tx["final_total"]) == 80.00
    assert tx["items"][0]["unit"] == "ML"
    assert float(tx["items"][0]["quantity"]) == 500.000
    assert float(tx["items"][0]["unit_price"]) == 0.16  # 160 / 1000 = 0.16 per ML
    assert float(tx["items"][0]["allocations"][0]["quantity_deducted"]) == 0.500

    # Remaining stock: 14.500 LITER
    prod_check = client.get(f"/api/v1/inventory/products/{prod_id}", headers=headers).json()
    assert float(prod_check["total_current_stock"]) == 14.500


def test_pos_selling_meter_length_units(client: TestClient, admin_headers: dict):
    """
    Product tracked in METER (e.g. Silk Ribbon, ₹50.00/METER).
    Customer buys 2.500 METERS.
    Expected: ₹125.00, batch deduction = 2.500 METER.
    """
    store_id, headers = setup_unit_test_store(client, admin_headers)
    today = date.today()

    p_resp = client.post(
        "/api/v1/inventory/products",
        json={"name": "Silk Ribbon", "category": "Fabrics", "default_unit": "METER", "selling_price": "50.00"},
        headers=headers,
    )
    prod_id = p_resp.json()["product_id"]

    client.post(
        "/api/v1/inventory/receive/single",
        json={
            "product_id": prod_id,
            "batch_identifier": "LOT-RIBBON-01",
            "quantity": "20.000",
            "purchase_date": today.isoformat(),
            "expiry_date": (today + timedelta(days=500)).isoformat(),
        },
        headers=headers,
    )

    tx = client.post(
        "/api/v1/billing/checkout",
        json={"items": [{"product_id": prod_id, "quantity": "2.500", "unit": "METER"}], "payment_method": "CASH"},
        headers=headers,
    ).json()
    assert float(tx["final_total"]) == 125.00
    assert tx["items"][0]["unit"] == "METER"

    prod_check = client.get(f"/api/v1/inventory/products/{prod_id}", headers=headers).json()
    assert float(prod_check["total_current_stock"]) == 17.500


def test_pos_rejects_incompatible_unit_checkout(client: TestClient, admin_headers: dict):
    """
    Validates that attempting to checkout a product using an incompatible unit
    (e.g. Sugar in KG requested in LITER) fails immediately with HTTP 400.
    """
    store_id, headers = setup_unit_test_store(client, admin_headers)
    today = date.today()

    p_resp = client.post(
        "/api/v1/inventory/products",
        json={"name": "Brown Sugar", "category": "Groceries", "default_unit": "KG", "selling_price": "75.00"},
        headers=headers,
    )
    prod_id = p_resp.json()["product_id"]

    client.post(
        "/api/v1/inventory/receive/single",
        json={
            "product_id": prod_id,
            "batch_identifier": "LOT-BSUGAR-01",
            "quantity": "10.000",
            "purchase_date": today.isoformat(),
            "expiry_date": (today + timedelta(days=365)).isoformat(),
        },
        headers=headers,
    )

    resp = client.post(
        "/api/v1/billing/checkout",
        json={"items": [{"product_id": prod_id, "quantity": "2.000", "unit": "LITER"}]},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "incompatible with product unit" in resp.json()["error"]["message"]


def test_validate_cart_stock_with_unit_conversion(client: TestClient, admin_headers: dict):
    """
    Tests /api/v1/billing/validate-stock with unit conversions:
    1. Product has 0.400 KG stock.
    2. Valid request: 300 GRAM (= 0.300 KG) -> Valid.
    3. Invalid request: 500 GRAM (= 0.500 KG) -> Invalid (only 0.400 KG available).
    4. Incompatible unit: 1 LITER -> Invalid.
    """
    store_id, headers = setup_unit_test_store(client, admin_headers)
    today = date.today()

    p_resp = client.post(
        "/api/v1/inventory/products",
        json={"name": "Specialty Tea", "category": "Beverages", "default_unit": "KG", "selling_price": "1200.00"},
        headers=headers,
    )
    prod_id = p_resp.json()["product_id"]

    # Stock only 0.400 KG
    client.post(
        "/api/v1/inventory/receive/single",
        json={
            "product_id": prod_id,
            "batch_identifier": "LOT-TEA-01",
            "quantity": "0.400",
            "purchase_date": today.isoformat(),
            "expiry_date": (today + timedelta(days=180)).isoformat(),
        },
        headers=headers,
    )

    # 1. Check 300 GRAM -> Sufficient (0.300 <= 0.400)
    v1 = client.post(
        "/api/v1/billing/validate-stock",
        json={"items": [{"product_id": prod_id, "quantity": "300.000", "unit": "GRAM"}]},
        headers=headers,
    ).json()
    assert v1["is_valid"] is True
    assert len(v1["errors"]) == 0

    # 2. Check 500 GRAM -> Insufficient (0.500 > 0.400)
    v2 = client.post(
        "/api/v1/billing/validate-stock",
        json={"items": [{"product_id": prod_id, "quantity": "500.000", "unit": "GRAM"}]},
        headers=headers,
    ).json()
    assert v2["is_valid"] is False
    assert len(v2["errors"]) == 1
    assert "Only 0.400 KG available in stock (requested 500.000 GRAM)" in v2["errors"][0]["message"]

    # 3. Check incompatible unit (5 DOZEN)
    v3 = client.post(
        "/api/v1/billing/validate-stock",
        json={"items": [{"product_id": prod_id, "quantity": "5.000", "unit": "DOZEN"}]},
        headers=headers,
    ).json()
    assert v3["is_valid"] is False
    assert len(v3["errors"]) == 1
    assert "incompatible with product unit" in v3["errors"][0]["message"]


def test_unit_calc_quantize_primitive_types():
    # Test float, int, str types
    assert quantize_quantity(1.5) == Decimal("1.500")
    assert quantize_quantity(2) == Decimal("2.000")
    assert quantize_quantity("0.125") == Decimal("0.125")

    assert quantize_currency(10.5) == Decimal("10.50")
    assert quantize_currency(5) == Decimal("5.00")
    assert quantize_currency("99.99") == Decimal("99.99")


def test_unit_calc_same_unit_and_cross_packaging_conversions():
    # Same unit
    assert UnitCalculator.convert_quantity(5, UnitEnum.KG, UnitEnum.KG) == Decimal("5.000")
    assert UnitCalculator.calculate_price_for_unit(100, UnitEnum.KG, UnitEnum.KG) == Decimal("100.00")

    # DOZEN to BOX (1 dozen = 12 pcs, 1 box = 12 pcs -> 1 box)
    assert UnitCalculator.convert_quantity(Decimal("1.000"), UnitEnum.DOZEN, UnitEnum.BOX, items_per_box=12) == Decimal("1.000")
    # DOZEN to BOX (1 dozen = 12 pcs, 1 box = 24 pcs -> 0.5 box)
    assert UnitCalculator.convert_quantity(Decimal("1.000"), UnitEnum.DOZEN, UnitEnum.BOX, items_per_box=24) == Decimal("0.500")
    # BOX of 24 to DOZEN -> 2.000 DOZEN
    assert UnitCalculator.convert_quantity(Decimal("1.000"), UnitEnum.BOX, UnitEnum.DOZEN, items_per_box=24) == Decimal("2.000")

    # Pricing: DOZEN to BOX
    # If 1 DOZEN costs 60.00, then 1 BOX of 24 pcs costs 120.00
    assert UnitCalculator.calculate_price_for_unit(Decimal("60.00"), UnitEnum.DOZEN, UnitEnum.BOX, items_per_box=24) == Decimal("120.00")
    # If 1 BOX of 24 costs 120.00, then 1 DOZEN costs 60.00
    assert UnitCalculator.calculate_price_for_unit(Decimal("120.00"), UnitEnum.BOX, UnitEnum.DOZEN, items_per_box=24) == Decimal("60.00")

    # Incompatible price conversion
    with pytest.raises(ValidationException):
        UnitCalculator.calculate_price_for_unit(100, UnitEnum.KG, UnitEnum.LITER)


def test_calculate_line_item_with_overrides_and_discounts():
    res = UnitCalculator.calculate_line_item(
        quantity=2,
        requested_unit=UnitEnum.PIECE,
        product_base_unit=UnitEnum.PIECE,
        product_selling_price=10.00,
        unit_price_override=15.00,
        item_discount_pct=Decimal("10.00"),
        category_discount_pct=Decimal("5.00"),
    )
    # line_base = 2 * 15.00 = 30.00
    # item_disc = 10% of 30.00 = 3.00 (remaining: 27.00)
    # cat_disc = 5% of 27.00 = 1.35
    # line_total = 27.00 - 1.35 = 25.65
    assert res["line_base_total"] == Decimal("30.00")
    assert res["item_discount_amount"] == Decimal("3.00")
    assert res["category_discount_amount"] == Decimal("1.35")
    assert res["line_total"] == Decimal("25.65")
