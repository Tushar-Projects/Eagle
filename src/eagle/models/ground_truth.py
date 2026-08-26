"""Ground-truth data contract for evaluation.

This module defines the shape of the ground-truth dataset used for
regression testing. The evaluator is not implemented here.
"""

from decimal import Decimal

from pydantic import BaseModel

from eagle.models.enums import (
    ExceptionType,
    ReconciliationOutcome,
    RelationshipType,
)


class GroundTruthRelationship(BaseModel):
    """A single ground-truth relationship for evaluation.

    MISSING_RECORD convention:
        When one side of a relationship has no counterpart, use an empty
        list for the absent side. This is symmetric:
        - Source exists, target missing: source_record_ids=["..."], target_record_ids=[]
        - Target exists, source missing: source_record_ids=[], target_record_ids=["..."]
        The relationship_type describes the *expected* structure (e.g. 1:1)
        even though one side is absent in the observed data.
        This convention also applies to predicted ReconciliationResult output.

    notes is documentation only and MUST NOT participate in
    evaluation logic.
    """

    relationship_id: str
    relationship_type: RelationshipType
    source_record_ids: list[str]
    target_record_ids: list[str]
    expected_outcome: ReconciliationOutcome
    expected_exception_type: ExceptionType | None = None
    expected_reconciled_amount: Decimal
    notes: str = ""


class GroundTruthDataset(BaseModel):
    """Top-level ground-truth dataset container."""

    relationships: list[GroundTruthRelationship]
