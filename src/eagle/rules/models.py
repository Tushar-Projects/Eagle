"""Domain models for operator corrections, feedback, and learned rules."""

from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel, Field, model_validator


class OperatorCorrection(BaseModel):
    """Represents an immutable, auditable human operator correction."""

    correction_id: str
    run_id: str
    relationship_id: str

    # Original decision snapshot
    original_outcome: str
    original_exception_type: Optional[str] = None
    original_source_ids: List[str] = Field(default_factory=list)
    original_target_ids: List[str] = Field(default_factory=list)

    # Corrected decision
    corrected_outcome: str
    corrected_exception_type: Optional[str] = None
    corrected_source_ids: List[str] = Field(default_factory=list)
    corrected_target_ids: List[str] = Field(default_factory=list)

    # Operator rationale and metadata
    operator_reason: str
    created_at: str
    generated_rule_id: Optional[str] = None


class ReconciliationRule(BaseModel):
    """Represents a generalized learned rule derived from operator corrections."""

    rule_id: str
    name: str
    description: str

    # Generalized Predicates (None acts as wildcard)
    source_counterparty_pattern: Optional[str] = None
    reference_prefix: Optional[str] = None
    currency: Optional[str] = None
    max_amount_difference: Optional[Decimal] = None
    max_settlement_delay_days: Optional[int] = None

    # Target Action & Resolution Semantics
    target_action: str = "PREFER_CANDIDATE"
    resulting_outcome: str = "MATCHED"
    resulting_exception_type: Optional[str] = None

    # Metadata & State
    confidence: float = 1.0
    is_active: bool = True
    created_at: str
    source_correction_id: Optional[str] = None

    @model_validator(mode="after")
    def _validate_rule_semantics(self) -> "ReconciliationRule":
        """Validate safety constraints, bounds, and predicate completeness."""
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"Rule confidence must be between 0.0 and 1.0, got {self.confidence}")

        if self.max_amount_difference is not None and self.max_amount_difference < Decimal("0.00"):
            raise ValueError(f"max_amount_difference cannot be negative, got {self.max_amount_difference}")

        if self.max_settlement_delay_days is not None and self.max_settlement_delay_days < 0:
            raise ValueError(f"max_settlement_delay_days cannot be negative, got {self.max_settlement_delay_days}")

        if self.target_action not in {"PREFER_CANDIDATE"}:
            raise ValueError(f"Unsupported target_action '{self.target_action}'. Must be 'PREFER_CANDIDATE'.")

        if self.resulting_outcome not in {"MATCHED", "EXCEPTION"}:
            raise ValueError(f"Unsupported resulting_outcome '{self.resulting_outcome}'. Must be 'MATCHED' or 'EXCEPTION'.")

        # Safety: A rule with zero predicates is unsafe and must be rejected
        predicates = (
            self.source_counterparty_pattern,
            self.reference_prefix,
            self.currency,
            self.max_amount_difference,
            self.max_settlement_delay_days,
        )
        if all(p is None for p in predicates):
            raise ValueError("Rule has no predicates specified. Rules must specify at least one generalized predicate.")

        return self
