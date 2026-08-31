"""Domain models for operator corrections and feedback."""

from typing import List, Optional
from pydantic import BaseModel, Field


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
