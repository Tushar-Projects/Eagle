from decimal import Decimal
from eagle.reconciliation.constants import (
    ROUNDING_TOLERANCE,
    FEE_MATCH_TOLERANCE,
    SETTLEMENT_NORMAL_WINDOW_DAYS,
    SETTLEMENT_DELAY_MEDIUM_MIN_DAYS,
    SETTLEMENT_DELAY_MEDIUM_MAX_DAYS,
    SETTLEMENT_DELAY_HIGH_MIN_DAYS,
)

def test_reconciliation_constants():
    assert ROUNDING_TOLERANCE == Decimal("1.00")
    assert FEE_MATCH_TOLERANCE == Decimal("2.00")
    assert SETTLEMENT_NORMAL_WINDOW_DAYS == 3
    assert SETTLEMENT_DELAY_MEDIUM_MIN_DAYS == 4
    assert SETTLEMENT_DELAY_MEDIUM_MAX_DAYS == 7
    assert SETTLEMENT_DELAY_HIGH_MIN_DAYS == 8
