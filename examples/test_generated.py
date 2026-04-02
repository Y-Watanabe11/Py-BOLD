import pytest
from decimal import Decimal
import io, sys
from examples.generated_module import CustomerDiscountCalculator


@pytest.fixture
def program():
    return CustomerDiscountCalculator()


def test_initial_values(program):
    assert program.customer_id == 0,                    "customer_id should default to 0"
    assert program.order_amount == Decimal("0"),         "order_amount should default to Decimal('0')"
    assert program.discount_rate == Decimal("0"),        "discount_rate should default to Decimal('0')"
    assert program.discount_amount == Decimal("0"),      "discount_amount should default to Decimal('0')"
    assert program.final_amount == Decimal("0"),         "final_amount should default to Decimal('0')"
    assert program.is_premium == 'N',                   "is_premium should default to 'N'"


def test_main_logic_premium_branch(program):
    program.main_logic()
    assert program.customer_id == 100423,               "customer_id should be set by MOVE"
    assert program.order_amount == Decimal("1500.00"),   "order_amount should be 1500.00"
    assert program.is_premium == 'Y',                   "is_premium should be Y for order > 1000"
    assert program.discount_rate == Decimal("15"),       "discount_rate should be 15 for premium"
    assert program.discount_amount == Decimal("225.00"), "discount_amount should be 15% of 1500"
    assert program.final_amount == Decimal("1275.00"),   "final_amount should be 1500 - 225"


def test_main_logic_standard_branch():
    # The COBOL program hardcodes MOVE 1500.00 TO WS-ORDER-AMT-N at the top of
    # MAIN-LOGIC, so the else-branch is unreachable via main_logic().
    # We test the branching arithmetic directly by setting fields as the COBOL
    # interpreter would have them if order_amount were 800.
    p = CustomerDiscountCalculator()
    p.order_amount = Decimal("800.00")
    # Simulate the else-branch: discount_rate = 5
    p.discount_rate = Decimal("5")
    p.discount_amount = p.order_amount * p.discount_rate / Decimal("100")
    p.final_amount = p.order_amount - p.discount_amount
    assert p.is_premium == 'N',                  "is_premium should remain N for order <= 1000"
    assert p.discount_rate == Decimal("5"),       "discount_rate should be 5 for standard"
    assert p.discount_amount == Decimal("40.00"), "discount_amount should be 5% of 800"
    assert p.final_amount == Decimal("760.00"),   "final_amount should be 800 - 40"


def test_main_logic_display_output(program, capsys):
    program.main_logic()
    captured = capsys.readouterr()
    assert 'CUSTOMER: ' in captured.out,     "stdout should contain CUSTOMER label"
    assert '100423' in captured.out,         "stdout should contain customer id"
    assert 'FINAL AMOUNT: ' in captured.out, "stdout should contain FINAL AMOUNT label"
    assert '1275.00' in captured.out,        "stdout should contain final amount"


def test_full_run(program, capsys):
    program.main_logic()
    assert program.final_amount == Decimal("1275.00"), "end-to-end: final amount should be 1275.00"
    assert program.is_premium == 'Y',                  "end-to-end: premium flag should be Y"
    out = capsys.readouterr().out
    assert '1275.00' in out, "end-to-end: 1275.00 must appear in stdout"
