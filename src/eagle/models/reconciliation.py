"""Reconciliation result domain models.

These are data contracts only. The reconciliation engine is not
implemented in this module.
"""

from decimal import Decimal

from pydantic import BaseModel

from eagle.models.enums import (
    ExceptionType,
    ReconciliationOutcome,
    RelationshipType,
    Severity,
)


class ReconciliationResult(BaseModel):
    """Result of reconciling a set of records.

    Outcome (MATCHED/EXCEPTION) is independent of exception_type.
    A MATCHED result can carry a classification (e.g. ROUNDING_DIFFERENCE).

    severity and flag_for_review apply to any record carrying
    a classification, not only settlement-delay cases.

    MISSING_RECORD convention:
        When a record has no counterpart, use an empty list for the
        absent side. Never use null, sentinels, or placeholder IDs.
        - Source exists, target missing: source_record_ids=["..."], target_record_ids=[]
        - Target exists, source missing: source_record_ids=[], target_record_ids=["..."]
        This matches the ground-truth representation so the evaluator
        can compare predicted vs. expected sets directly.
    """

    relationship_id: str
    relationship_type: RelationshipType
    source_record_ids: list[str]
    target_record_ids: list[str]
    outcome: ReconciliationOutcome
    exception_type: ExceptionType | None = None
    severity: Severity | None = None
    flag_for_review: bool = False
    reconciled_amount: Decimal | None = None
