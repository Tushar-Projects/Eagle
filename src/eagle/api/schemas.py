"""Pydantic schemas for the Eagle FastAPI REST API."""

from decimal import Decimal
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class RunResponse(BaseModel):
    """Reconciliation run summary response."""
    run_id: str
    status: str
    created_at: str
    completed_at: Optional[str] = None
    total_records: int = 0
    source_count: int = 0
    target_count: int = 0
    matched_count: int = 0
    exception_count: int = 0
    missing_count: int = 0
    unresolved_count: int = 0
    ai_provider: str = ""
    error_message: Optional[str] = None


class RunListResponse(BaseModel):
    """List of reconciliation runs."""
    runs: List[RunResponse]
    total: int


class ReconciliationResultResponse(BaseModel):
    """Reconciliation relationship item response."""
    relationship_id: str
    source_record_ids: List[str]
    target_record_ids: List[str]
    relationship_type: str
    outcome: str
    exception_type: Optional[str] = None
    severity: Optional[str] = None
    flag_for_review: bool = False
    reconciled_amount: Optional[str] = None
    provenance: str = "DETERMINISTIC"


class ResultsListResponse(BaseModel):
    """List of reconciliation results for a run."""
    run_id: str
    results: List[ReconciliationResultResponse]
    total: int


class CandidateOptionItem(BaseModel):
    """A deterministic candidate option within an unresolved pool."""
    index: int
    source_record_ids: List[str]
    target_record_ids: List[str]


class CandidateDecisionResponse(BaseModel):
    """Candidate pool decision, reasoning, and validation status."""
    id: Optional[int] = None
    run_id: str
    anchor_record_id: str
    candidate_options: List[CandidateOptionItem]
    selected_candidate_index: Optional[int] = None
    ai_outcome: Optional[str] = None
    ai_exception_type: Optional[str] = None
    confidence: Optional[float] = None
    reasoning: str = ""
    validation_status: str
    rejection_reason: Optional[str] = None


class CandidateListResponse(BaseModel):
    """List of candidate pools and decisions for a run."""
    run_id: str
    candidates: List[CandidateDecisionResponse]
    total: int


class RunMetricsResponse(BaseModel):
    """Product-facing KPI and reconciliation metrics for a run."""
    run_id: str
    status: str
    total_records: int
    source_count: int
    target_count: int
    matched_count: int
    exception_count: int
    missing_count: int
    unresolved_count: int
    match_rate: float
    exception_rate: float
    value_weighted_match_rate: float = 0.0
    total_reconciled_amount: str


class AuditEventResponse(BaseModel):
    """Audit log entry response."""
    id: Optional[int] = None
    run_id: str
    timestamp: str
    event_type: str
    details: Optional[Dict[str, Any]] = None


class JsonRunCreateRequest(BaseModel):
    """Optional JSON payload for submitting source and target records directly."""
    source_records: List[Dict[str, Any]]
    target_records: List[Dict[str, Any]]


# ---------------------------------------------------------------------------
# Operator Corrections
# ---------------------------------------------------------------------------

class CorrectionCreateRequest(BaseModel):
    """Request payload for an operator submitting a manual correction."""
    corrected_outcome: str = Field(..., description="Target outcome: MATCHED or EXCEPTION")
    corrected_exception_type: Optional[str] = Field(None, description="Optional ExceptionType classification")
    corrected_source_ids: List[str] = Field(default_factory=list, description="Source record IDs involved in corrected relationship")
    corrected_target_ids: List[str] = Field(default_factory=list, description="Target record IDs involved in corrected relationship")
    operator_reason: str = Field(..., min_length=3, description="Mandatory operator explanation/rationale")
    generate_rule: bool = Field(False, description="Flag indicating intent to synthesize a rule (handled in Day 2)")


class OperatorCorrectionResponse(BaseModel):
    """Response model representing a persisted operator correction."""
    correction_id: str
    run_id: str
    relationship_id: str
    original_outcome: str
    original_exception_type: Optional[str] = None
    original_source_ids: List[str]
    original_target_ids: List[str]
    corrected_outcome: str
    corrected_exception_type: Optional[str] = None
    corrected_source_ids: List[str]
    corrected_target_ids: List[str]
    operator_reason: str
    created_at: str
    status: str = "COMMITTED"
    generated_rule_id: Optional[str] = None


class CorrectionListResponse(BaseModel):
    """List of operator corrections for a run."""
    run_id: str
    corrections: List[OperatorCorrectionResponse]
    total: int


class ErrorResponse(BaseModel):
    """Standard error response."""
    error: str
    detail: Optional[str] = None

