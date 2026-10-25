from decimal import Decimal

from app.utils.number_to_words import number_to_words_inr


def test_zero_amount():
    assert number_to_words_inr(0) == "Zero Rupees only"
    assert number_to_words_inr("0.00") == "Zero Rupees only"
    assert number_to_words_inr(Decimal("0.00")) == "Zero Rupees only"


def test_single_rupee():
    assert number_to_words_inr(1) == "One Rupee only"
    assert number_to_words_inr("1.00") == "One Rupee only"


def test_plural_rupees_simple():
    assert number_to_words_inr(5) == "Five Rupees only"
    assert number_to_words_inr(15) == "Fifteen Rupees only"
    assert number_to_words_inr(25) == "Twenty Five Rupees only"
    assert number_to_words_inr(99) == "Ninety Nine Rupees only"


def test_hundreds():
    assert number_to_words_inr(100) == "One Hundred Rupees only"
    assert number_to_words_inr(105) == "One Hundred and Five Rupees only"
    assert number_to_words_inr(350) == "Three Hundred and Fifty Rupees only"
    assert number_to_words_inr(999) == "Nine Hundred and Ninety Nine Rupees only"


def test_thousands():
    assert number_to_words_inr(1000) == "One Thousand Rupees only"
    assert number_to_words_inr(1001) == "One Thousand One Rupees only"
    assert number_to_words_inr(1500) == "One Thousand Five Hundred Rupees only"
    assert number_to_words_inr(25420) == "Twenty Five Thousand Four Hundred and Twenty Rupees only"


def test_lakhs_and_crores():
    # 1 Lakh = 100,000
    assert number_to_words_inr(100000) == "One Lakh Rupees only"
    assert number_to_words_inr(550000) == "Five Lakh Fifty Thousand Rupees only"

    # 1 Crore = 10,000,000
    assert number_to_words_inr(10000000) == "One Crore Rupees only"
    assert number_to_words_inr(12345678) == "One Crore Twenty Three Lakh Forty Five Thousand Six Hundred and Seventy Eight Rupees only"


def test_paise_only():
    assert number_to_words_inr(0.50) == "Fifty Paisa only"
    assert number_to_words_inr("0.05") == "Five Paisa only"
    assert number_to_words_inr(Decimal("0.99")) == "Ninety Nine Paisa only"


def test_rupees_and_paise():
    assert number_to_words_inr(132.30) == "One Hundred and Thirty Two Rupees and Thirty Paisa only"
    assert number_to_words_inr("1.01") == "One Rupee and One Paisa only"
    assert number_to_words_inr(Decimal("45.50")) == "Forty Five Rupees and Fifty Paisa only"


def test_negative_amounts():
    assert number_to_words_inr(-10) == "Negative Ten Rupees only"
    assert number_to_words_inr("-50.25") == "Negative Fifty Rupees and Twenty Five Paisa only"


def test_invalid_input_fallback():
    assert number_to_words_inr("invalid-string") == "Zero Rupees only"
    assert number_to_words_inr(None) == "Zero Rupees only"
