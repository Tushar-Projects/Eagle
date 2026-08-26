"""AI classifier input/output contracts.

These models define the structured interface between the deterministic
reconciliation engine and the AI exception classifier. They are
orchestration-layer contracts, NOT frozen domain models.
"""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from eagle.models.reconciliation import ReconciliationResult


# ---------------------------------------------------------------------------
# AI Input
# ---------------------------------------------------------------------------


class ClassificationCase(BaseModel):
    """A single case presented to the AI classifier.

    Contains all evidence the AI needs to reason about
    the case, without access to ground truth.
    """

    case_type: Literal["EXCEPTION_CLASSIFICATION", "CANDIDATE_SELECTION"]

    # Identity — who is involved
    source_record_ids: list[str]
    committed_target_record_ids: list[str]      # For EXCEPTION_CLASSIFICATION
    candidate_target_record_ids: list[str]       # For CANDIDATE_SELECTION

    # Committed topology (only for EXCEPTION_CLASSIFICATION)
    committed_relationship_type: str | None = None

    # Financial evidence
    source_amounts: list[Decimal]
    source_currencies: list[str]
    target_amounts: list[Decimal]
    target_currencies: list[str]

    # Timing evidence
    source_transaction_dates: list[str]
    target_settlement_dates: list[str]

    # Deterministic context
    evidence_summary: str


# ---------------------------------------------------------------------------
# AI Decision — narrowly scoped to what the AI actually decides
# ---------------------------------------------------------------------------


class ExceptionClassificationDecision(BaseModel):
    """AI decision for exception classification.

    The AI decides ONLY classification fields. Participant IDs,
    topology, and reconciled amount are preserved from the
    deterministic engine and are NOT part of this contract.
    """

    exception_type: str | None
    severity: str | None
    flag_for_review: bool
    reasoning: str
    confidence: float  # Model-reported signal, NOT a calibrated probability


class CandidateSelectionDecision(BaseModel):
    """AI decision for resolving an ambiguous candidate pool.

    selected_target_record_ids must be a subset of the
    candidate_target_record_ids supplied in ClassificationCase.
    An empty list means the AI found no valid counterpart.
    """

    selected_target_record_ids: list[str]
    relationship_type: str
    outcome: str
    exception_type: str | None
    severity: str | None
    flag_for_review: bool
    reconciled_amount: str   # String → parsed to Decimal by the application
    reasoning: str
    confidence: float  # Model-reported signal, NOT a calibrated probability


# ---------------------------------------------------------------------------
# Classifier Output
# ---------------------------------------------------------------------------


class FailedClassification(BaseModel):
    """Records an AI classification failure for audit/review."""

    source_record_ids: list[str]
    candidate_target_record_ids: list[str]
    case_type: str
    failure_reason: str
    attempts: int


class ClassifierOutput(BaseModel):
    """Output of the AI classifier stage.

    classified_results: AI-produced committed ReconciliationResult objects.
    failed_cases: Cases where AI classification failed after retries.
    """

    classified_results: list[ReconciliationResult]
    failed_cases: list[FailedClassification]
