from decimal import Decimal

ONES = [
    "",
    "One",
    "Two",
    "Three",
    "Four",
    "Five",
    "Six",
    "Seven",
    "Eight",
    "Nine",
    "Ten",
    "Eleven",
    "Twelve",
    "Thirteen",
    "Fourteen",
    "Fifteen",
    "Sixteen",
    "Seventeen",
    "Eighteen",
    "Nineteen",
]

TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _two_digits_to_words(n: int) -> str:
    if n < 20:
        return ONES[n]
    tens = TENS[n // 10]
    ones = ONES[n % 10]
    return f"{tens} {ones}".strip() if ones else tens


def _three_digits_to_words(n: int) -> str:
    hundreds = n // 100
    remainder = n % 100
    parts = []
    if hundreds > 0:
        parts.append(f"{ONES[hundreds]} Hundred")
    if remainder > 0:
        if parts:
            parts.append("and")
        parts.append(_two_digits_to_words(remainder))
    return " ".join(parts)


def number_to_words_inr(amount: float | Decimal | int | str) -> str:
    """
    Converts a currency amount to Indian English words.
    Example: 132.30 -> "One Hundred and Thirty Two Rupees and Thirty Paisa only"
             1500.00 -> "One Thousand Five Hundred Rupees only"
             0.00 -> "Zero Rupees only"
    """
    try:
        dec = Decimal(str(amount)).quantize(Decimal("0.01"))
    except Exception:
        return "Zero Rupees only"

    if dec < 0:
        return f"Negative {number_to_words_inr(abs(dec))}"

    rupees = int(dec)
    paise = int(round((dec - rupees) * 100))

    if rupees == 0 and paise == 0:
        return "Zero Rupees only"

    words_parts = []

    if rupees > 0:
        # Indian Numbering System:
        # Crores (10,000,000)
        # Lakhs (100,000)
        # Thousands (1,000)
        # Hundreds (100)
        crores = rupees // 10000000
        rem = rupees % 10000000

        lakhs = rem // 100000
        rem = rem % 100000

        thousands = rem // 1000
        rem = rem % 1000

        hundreds_and_below = rem

        if crores > 0:
            words_parts.append(f"{_three_digits_to_words(crores)} Crore")
        if lakhs > 0:
            words_parts.append(f"{_two_digits_to_words(lakhs)} Lakh")
        if thousands > 0:
            words_parts.append(f"{_two_digits_to_words(thousands)} Thousand")
        if hundreds_and_below > 0:
            words_parts.append(_three_digits_to_words(hundreds_and_below))

        rupee_str = " ".join(words_parts) + (" Rupee" if rupees == 1 else " Rupees")
    else:
        rupee_str = ""

    paise_str = ""
    if paise > 0:
        paise_words = _two_digits_to_words(paise)
        paise_str = f"{paise_words} Paisa"

    if rupee_str and paise_str:
        return f"{rupee_str} and {paise_str} only"
    elif rupee_str:
        return f"{rupee_str} only"
    else:
        return f"{paise_str} only"
