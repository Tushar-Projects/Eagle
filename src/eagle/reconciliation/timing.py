"""Settlement timing logic for deterministic classification."""
from datetime import date
from typing import Tuple

from eagle.models.enums import ExceptionType, ReconciliationOutcome, Severity
from eagle.reconciliation.constants import (
    SETTLEMENT_DELAY_HIGH_MIN_DAYS,
    SETTLEMENT_DELAY_MEDIUM_MAX_DAYS,
    SETTLEMENT_DELAY_MEDIUM_MIN_DAYS,
    SETTLEMENT_NORMAL_WINDOW_DAYS,
)


def evaluate_settlement_timing(
    transaction_date: date, settlement_date: date
) -> Tuple[ReconciliationOutcome, ExceptionType | None, Severity | None, bool]:
    """Evaluate settlement timing and return classification attributes.

    Returns:
        Tuple of (outcome, exception_type, severity, flag_for_review)
    """
    delay_days = (settlement_date - transaction_date).days

    if delay_days < 0:
        # Invalid chronological order (e.g. settlement before transaction)
        return ReconciliationOutcome.EXCEPTION, None, Severity.HIGH, True

    if delay_days <= SETTLEMENT_NORMAL_WINDOW_DAYS:
        return ReconciliationOutcome.MATCHED, None, None, False

    if SETTLEMENT_DELAY_MEDIUM_MIN_DAYS <= delay_days <= SETTLEMENT_DELAY_MEDIUM_MAX_DAYS:
        return (
            ReconciliationOutcome.MATCHED,
            ExceptionType.SETTLEMENT_DELAY,
            Severity.MEDIUM,
            False,
        )

    if delay_days >= SETTLEMENT_DELAY_HIGH_MIN_DAYS:
        return (
            ReconciliationOutcome.MATCHED,
            ExceptionType.SETTLEMENT_DELAY,
            Severity.HIGH,
            True,
        )

    # Fallback for unexpected gaps, though logically covered above
    return ReconciliationOutcome.MATCHED, None, None, False
