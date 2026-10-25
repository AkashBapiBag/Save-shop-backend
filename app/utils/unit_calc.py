from decimal import ROUND_HALF_UP, Decimal
from enum import Enum

from app.core.exceptions import ValidationException
from app.models.inventory import UnitEnum

TWO_PLACES = Decimal("0.01")
THREE_PLACES = Decimal("0.001")


class UnitDimension(str, Enum):
    WEIGHT = "WEIGHT"
    VOLUME = "VOLUME"
    COUNT = "COUNT"
    PACKAGING = "PACKAGING"
    LENGTH = "LENGTH"


# Mapping from UnitEnum to its Physical Dimension
UNIT_DIMENSION_MAP: dict[UnitEnum, UnitDimension] = {
    UnitEnum.KG: UnitDimension.WEIGHT,
    UnitEnum.GRAM: UnitDimension.WEIGHT,
    UnitEnum.LITER: UnitDimension.VOLUME,
    UnitEnum.ML: UnitDimension.VOLUME,
    UnitEnum.DOZEN: UnitDimension.COUNT,
    UnitEnum.PIECE: UnitDimension.COUNT,
    UnitEnum.PACKET: UnitDimension.PACKAGING,
    UnitEnum.BOX: UnitDimension.PACKAGING,
    UnitEnum.BOTTLE: UnitDimension.PACKAGING,
    UnitEnum.CAN: UnitDimension.PACKAGING,
    UnitEnum.METER: UnitDimension.LENGTH,
}

# Conversion multipliers to canonical base unit:
# - Weight base: KG (1 KG = 1.0, 1 GRAM = 0.001)
# - Volume base: LITER (1 LITER = 1.0, 1 ML = 0.001)
# - Count base: PIECE (1 PIECE = 1.0, 1 DOZEN = 12.0)
# - Length base: METER (1 METER = 1.0)
CANONICAL_FACTORS: dict[UnitEnum, Decimal] = {
    UnitEnum.KG: Decimal("1.000"),
    UnitEnum.GRAM: Decimal("0.001"),
    UnitEnum.LITER: Decimal("1.000"),
    UnitEnum.ML: Decimal("0.001"),
    UnitEnum.DOZEN: Decimal("12.000"),
    UnitEnum.PIECE: Decimal("1.000"),
    UnitEnum.METER: Decimal("1.000"),
}


def quantize_quantity(qty: Decimal | float | int | str) -> Decimal:
    """
    Quantizes a quantity to exactly 3 decimal places (e.g. 0.250 KG, 1.500 DOZEN).
    """
    if not isinstance(qty, Decimal):
        qty = Decimal(str(qty))
    return qty.quantize(THREE_PLACES, rounding=ROUND_HALF_UP)


def quantize_currency(amount: Decimal | float | int | str) -> Decimal:
    """
    Quantizes a currency amount to exactly 2 decimal places (e.g. ₹25.50).
    """
    if not isinstance(amount, Decimal):
        amount = Decimal(str(amount))
    return amount.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


class UnitCalculator:
    """
    Production-grade Unit Conversion and Calculation Engine.
    Handles exact calculations for all retail units (KG, GRAM, LITER, ML, DOZEN, PIECE, BOX, PACKET, etc.)
    with Decimal precision, rounding, and validation.
    """

    @staticmethod
    def normalize_unit(unit: UnitEnum | str) -> UnitEnum:
        """
        Normalizes a string or UnitEnum instance to the canonical UnitEnum.
        Handles case-insensitive matches (e.g. 'kg' -> UnitEnum.KG, 'dozen' -> UnitEnum.DOZEN).
        """
        if isinstance(unit, UnitEnum):
            return unit
        if isinstance(unit, str):
            clean_str = unit.strip().upper()
            try:
                return UnitEnum(clean_str)
            except ValueError:
                # Handle plural variations
                plurals = {
                    "KGS": UnitEnum.KG,
                    "KILOGRAM": UnitEnum.KG,
                    "KILOGRAMS": UnitEnum.KG,
                    "GRAMS": UnitEnum.GRAM,
                    "GM": UnitEnum.GRAM,
                    "GMS": UnitEnum.GRAM,
                    "LITERS": UnitEnum.LITER,
                    "LITRE": UnitEnum.LITER,
                    "LITRES": UnitEnum.LITER,
                    "MLS": UnitEnum.ML,
                    "MILLILITER": UnitEnum.ML,
                    "MILLILITERS": UnitEnum.ML,
                    "DOZENS": UnitEnum.DOZEN,
                    "DOZ": UnitEnum.DOZEN,
                    "PIECES": UnitEnum.PIECE,
                    "PCS": UnitEnum.PIECE,
                    "PC": UnitEnum.PIECE,
                    "BOXES": UnitEnum.BOX,
                    "PACKETS": UnitEnum.PACKET,
                    "PKT": UnitEnum.PACKET,
                    "PKTS": UnitEnum.PACKET,
                    "BOTTLES": UnitEnum.BOTTLE,
                    "BTL": UnitEnum.BOTTLE,
                    "CANS": UnitEnum.CAN,
                    "METERS": UnitEnum.METER,
                    "METRE": UnitEnum.METER,
                    "METRES": UnitEnum.METER,
                    "M": UnitEnum.METER,
                }
                if clean_str in plurals:
                    return plurals[clean_str]
                raise ValidationException(f"Unsupported measurement unit '{unit}'. Supported: {[u.value for u in UnitEnum]}") from None
        raise ValidationException(f"Invalid unit type: {type(unit)}")

    @staticmethod
    def get_dimension(unit: UnitEnum | str) -> UnitDimension:
        norm_unit = UnitCalculator.normalize_unit(unit)
        return UNIT_DIMENSION_MAP[norm_unit]

    @classmethod
    def is_compatible(cls, from_unit: UnitEnum | str, to_unit: UnitEnum | str) -> bool:
        """
        Returns True if from_unit and to_unit can be converted to each other.
        - Units in the same physical dimension (Weight, Volume, Count, Length) are directly compatible.
        - Packaging units (BOX, PACKET, BOTTLE, CAN) are compatible with PIECE (or with each other when items_per_box is known).
        """
        try:
            u_from = cls.normalize_unit(from_unit)
            u_to = cls.normalize_unit(to_unit)
        except Exception:
            return False

        if u_from == u_to:
            return True

        dim_from = cls.get_dimension(u_from)
        dim_to = cls.get_dimension(u_to)

        # Same physical dimension
        if dim_from == dim_to and dim_from in (UnitDimension.WEIGHT, UnitDimension.VOLUME, UnitDimension.COUNT, UnitDimension.LENGTH):
            return True

        # Cross-compatibility: COUNT (PIECE) and PACKAGING (BOX, PACKET, BOTTLE, CAN)
        if (
            (dim_from == UnitDimension.COUNT and dim_to == UnitDimension.PACKAGING)
            or (dim_from == UnitDimension.PACKAGING and dim_to == UnitDimension.COUNT)
            or (dim_from == UnitDimension.PACKAGING and dim_to == UnitDimension.PACKAGING)
        ):
            return True

        return False

    @classmethod
    def convert_quantity(
        cls,
        quantity: Decimal | float | int | str,
        from_unit: UnitEnum | str,
        to_unit: UnitEnum | str,
        items_per_box: int = 12,
    ) -> Decimal:
        """
        Converts quantity from `from_unit` to `to_unit`.
        Examples:
        - 1.500 KG -> 1500.000 GRAM
        - 250.000 GRAM -> 0.250 KG
        - 0.500 DOZEN -> 6.000 PIECE
        - 18.000 PIECE -> 1.500 DOZEN
        - 2.000 BOX (items_per_box=24) -> 48.000 PIECE
        - 12.000 PIECE (items_per_box=24) -> 0.500 BOX
        """
        if not isinstance(quantity, Decimal):
            quantity = Decimal(str(quantity))

        if quantity < Decimal("0.000"):
            raise ValidationException(f"Quantity cannot be negative: {quantity}")

        u_from = cls.normalize_unit(from_unit)
        u_to = cls.normalize_unit(to_unit)

        if u_from == u_to:
            return quantize_quantity(quantity)

        if not cls.is_compatible(u_from, u_to):
            raise ValidationException(
                f"Cannot convert between incompatible units: '{u_from.value}' ({cls.get_dimension(u_from).value}) and '{u_to.value}' ({cls.get_dimension(u_to).value})"
            )

        dim_from = cls.get_dimension(u_from)
        dim_to = cls.get_dimension(u_to)

        # Weight conversion: KG <-> GRAM
        if dim_from == UnitDimension.WEIGHT and dim_to == UnitDimension.WEIGHT:
            base_kg = quantity * CANONICAL_FACTORS[u_from]
            converted = base_kg / CANONICAL_FACTORS[u_to]
            return quantize_quantity(converted)

        # Volume conversion: LITER <-> ML
        if dim_from == UnitDimension.VOLUME and dim_to == UnitDimension.VOLUME:
            base_liter = quantity * CANONICAL_FACTORS[u_from]
            converted = base_liter / CANONICAL_FACTORS[u_to]
            return quantize_quantity(converted)

        # Count conversion: DOZEN <-> PIECE
        if dim_from == UnitDimension.COUNT and dim_to == UnitDimension.COUNT:
            base_pieces = quantity * CANONICAL_FACTORS[u_from]
            converted = base_pieces / CANONICAL_FACTORS[u_to]
            return quantize_quantity(converted)

        # Packaging / Count conversion: BOX <-> PIECE / DOZEN / PACKET
        box_multiplier = Decimal(str(items_per_box if items_per_box > 0 else 12))

        # First convert u_from to pieces
        if u_from == UnitEnum.BOX:
            pieces = quantity * box_multiplier
        elif u_from == UnitEnum.DOZEN:
            pieces = quantity * Decimal("12.000")
        elif u_from in (UnitEnum.PIECE, UnitEnum.PACKET, UnitEnum.BOTTLE, UnitEnum.CAN):
            pieces = quantity
        else:
            raise ValidationException(f"Unsupported conversion from {u_from.value}")

        # Now convert pieces to u_to
        if u_to == UnitEnum.BOX:
            converted = pieces / box_multiplier
        elif u_to == UnitEnum.DOZEN:
            converted = pieces / Decimal("12.000")
        elif u_to in (UnitEnum.PIECE, UnitEnum.PACKET, UnitEnum.BOTTLE, UnitEnum.CAN):
            converted = pieces
        else:
            raise ValidationException(f"Unsupported conversion to {u_to.value}")

        return quantize_quantity(converted)

    @classmethod
    def calculate_price_for_unit(
        cls,
        base_price: Decimal | float | int | str,
        from_unit: UnitEnum | str,
        to_unit: UnitEnum | str,
        items_per_box: int = 12,
    ) -> Decimal:
        """
        Calculates the unit price in `to_unit` when `base_price` is quoted per `from_unit`.
        Examples:
        - If sugar is ₹80.00 per KG:
          1 GRAM costs ₹80.00 / 1000 = ₹0.08 per GRAM.
        - If eggs are ₹120.00 per DOZEN:
          1 PIECE costs ₹120.00 / 12 = ₹10.00 per PIECE.
        - If mangoes are ₹240.00 per BOX of 24 pieces:
          1 PIECE costs ₹240.00 / 24 = ₹10.00 per PIECE.
        - If milk is ₹60.00 per LITER:
          1 ML costs ₹60.00 / 1000 = ₹0.06 per ML.
        """
        if not isinstance(base_price, Decimal):
            base_price = Decimal(str(base_price))

        if base_price < Decimal("0.00"):
            raise ValidationException(f"Price cannot be negative: {base_price}")

        u_from = cls.normalize_unit(from_unit)
        u_to = cls.normalize_unit(to_unit)

        if u_from == u_to:
            return quantize_currency(base_price)

        if not cls.is_compatible(u_from, u_to):
            raise ValidationException(f"Cannot convert price between incompatible units: '{u_from.value}' and '{u_to.value}'")

        dim_from = cls.get_dimension(u_from)
        dim_to = cls.get_dimension(u_to)

        # Weight: KG <-> GRAM
        if dim_from == UnitDimension.WEIGHT and dim_to == UnitDimension.WEIGHT:
            factor = CANONICAL_FACTORS[u_to] / CANONICAL_FACTORS[u_from]
            return quantize_currency(base_price * factor)

        # Volume: LITER <-> ML
        if dim_from == UnitDimension.VOLUME and dim_to == UnitDimension.VOLUME:
            factor = CANONICAL_FACTORS[u_to] / CANONICAL_FACTORS[u_from]
            return quantize_currency(base_price * factor)

        # Count: DOZEN <-> PIECE
        if dim_from == UnitDimension.COUNT and dim_to == UnitDimension.COUNT:
            factor = CANONICAL_FACTORS[u_to] / CANONICAL_FACTORS[u_from]
            return quantize_currency(base_price * factor)

        # Packaging / Count: BOX <-> PIECE / DOZEN / PACKET
        box_multiplier = Decimal(str(items_per_box if items_per_box > 0 else 12))

        if u_from == UnitEnum.BOX:
            pieces_in_from = box_multiplier
        elif u_from == UnitEnum.DOZEN:
            pieces_in_from = Decimal("12.0")
        else:
            pieces_in_from = Decimal("1.0")

        if u_to == UnitEnum.BOX:
            pieces_in_to = box_multiplier
        elif u_to == UnitEnum.DOZEN:
            pieces_in_to = Decimal("12.0")
        else:
            pieces_in_to = Decimal("1.0")

        target_price = (base_price / pieces_in_from) * pieces_in_to
        return quantize_currency(target_price)

    @classmethod
    def calculate_line_item(
        cls,
        quantity: Decimal | float | int | str,
        requested_unit: UnitEnum | str,
        product_base_unit: UnitEnum | str,
        product_selling_price: Decimal | float | int | str,
        unit_price_override: Decimal | float | int | str | None = None,
        item_discount_pct: Decimal = Decimal("0.00"),
        category_discount_pct: Decimal = Decimal("0.00"),
        items_per_box: int = 12,
    ) -> dict[str, Decimal]:
        """
        Computes the complete line item financials and stock deduction quantity:
        - converted_deduction_qty: quantity in product's base unit to deduct from batches.
        - line_base_total: base total before discounts.
        - item_discount_amount: discount from item %
        - category_discount_amount: discount from category %
        - line_total: final total for this line
        """
        qty = Decimal(str(quantity))
        u_req = cls.normalize_unit(requested_unit)
        u_base = cls.normalize_unit(product_base_unit)

        # Convert requested quantity to product's stock tracking base unit
        deduction_qty = cls.convert_quantity(qty, from_unit=u_req, to_unit=u_base, items_per_box=items_per_box)

        # Determine unit price:
        if unit_price_override is not None:
            eff_unit_price = quantize_currency(unit_price_override)
            line_base = quantize_currency(qty * eff_unit_price)
        else:
            base_price = Decimal(str(product_selling_price))
            # Price can be computed either as deduction_qty * base_price or qty * converted_price
            line_base = quantize_currency(deduction_qty * base_price)
            eff_unit_price = quantize_currency(line_base / qty) if qty > Decimal("0.000") else base_price

        # Discounts
        it_disc_amt = quantize_currency(line_base * (item_discount_pct / Decimal("100")))
        price_after_it = max(Decimal("0.00"), line_base - it_disc_amt)

        cat_disc_amt = quantize_currency(price_after_it * (category_discount_pct / Decimal("100")))
        line_final = max(Decimal("0.00"), price_after_it - cat_disc_amt)

        return {
            "requested_quantity": quantize_quantity(qty),
            "requested_unit": u_req,
            "product_base_unit": u_base,
            "deduction_quantity": deduction_qty,
            "unit_price": eff_unit_price,
            "line_base_total": line_base,
            "item_discount_amount": it_disc_amt,
            "category_discount_amount": cat_disc_amt,
            "total_line_discount": it_disc_amt + cat_disc_amt,
            "line_total": line_final,
        }

    @classmethod
    def format_quantity_display(cls, quantity: Decimal | float | int | str, unit: UnitEnum | str) -> str:
        """
        Formats quantity with unit label for receipts and UI displays.
        e.g. '0.500 KG', '12 PIECE', '1.500 DOZEN', '2 BOX'
        """
        norm_unit = cls.normalize_unit(unit)
        q = quantize_quantity(quantity)
        return f"{q} {norm_unit.value}"
