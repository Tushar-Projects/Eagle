"""Domain enums for the Eagle reconciliation system."""

from enum import Enum


class RelationshipType(str, Enum):
    """Supported reconciliation relationship types.

    General N:M relationships are out of scope.
    """

    ONE_TO_ONE = "1:1"
    ONE_TO_MANY = "1:N"
    MANY_TO_ONE = "N:1"


class ReconciliationOutcome(str, Enum):
    """Outcome of a reconciliation match attempt.

    Outcome is independent of classification/exception type.
    A MATCHED outcome can still carry a classification
    (e.g. ROUNDING_DIFFERENCE or FEE_DEDUCTION).
    """

    MATCHED = "MATCHED"
    EXCEPTION = "EXCEPTION"


class ExceptionType(str, Enum):
    """Closed AI exception taxonomy.

    VALIDATION_EXCEPTION is NOT part of this taxonomy.
    Validation errors (e.g. settlement date preceding transaction date)
    are handled separately and deterministically.

    DUPLICATE represents deterministic duplicate evidence.
    POSSIBLE_DUPLICATE represents AI uncertainty without sufficient
    deterministic evidence.
    """

    SETTLEMENT_DELAY = "SETTLEMENT_DELAY"
    FEE_DEDUCTION = "FEE_DEDUCTION"
    ROUNDING_DIFFERENCE = "ROUNDING_DIFFERENCE"
    PARTIAL_SETTLEMENT = "PARTIAL_SETTLEMENT"
    SPLIT_SETTLEMENT = "SPLIT_SETTLEMENT"
    DUPLICATE = "DUPLICATE"
    MISSING_RECORD = "MISSING_RECORD"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    POSSIBLE_DUPLICATE = "POSSIBLE_DUPLICATE"
    UNKNOWN = "UNKNOWN"


class Severity(str, Enum):
    """Severity level for any record carrying a classification or exception type.

    Not restricted to settlement-delay cases.
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
