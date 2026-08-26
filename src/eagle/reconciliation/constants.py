"""
Reconciliation constants defined by the Eagle architecture specification.
These values must remain version-controlled and reproducible.
"""
from typing import Final
from decimal import Decimal

# Tolerances
ROUNDING_TOLERANCE: Final[Decimal] = Decimal("1.00")
FEE_MATCH_TOLERANCE: Final[Decimal] = Decimal("2.00")

# Settlement Timing Thresholds
SETTLEMENT_NORMAL_WINDOW_DAYS: Final[int] = 3
SETTLEMENT_DELAY_MEDIUM_MIN_DAYS: Final[int] = 4
SETTLEMENT_DELAY_MEDIUM_MAX_DAYS: Final[int] = 7
SETTLEMENT_DELAY_HIGH_MIN_DAYS: Final[int] = 8
