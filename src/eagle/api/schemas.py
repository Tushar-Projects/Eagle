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


# ---------------------------------------------------------------------------
# Reconciliation Rules
# ---------------------------------------------------------------------------

class RuleResponse(BaseModel):
    """Response model representing a learned reconciliation rule."""
    rule_id: str
    name: str
    description: str
    source_counterparty_pattern: Optional[str] = None
    reference_prefix: Optional[str] = None
    currency: Optional[str] = None
    max_amount_difference: Optional[Decimal] = None
    max_settlement_delay_days: Optional[int] = None
    target_action: str = "PREFER_CANDIDATE"
    resulting_outcome: str = "MATCHED"
    resulting_exception_type: Optional[str] = None
    confidence: float = 1.0
    is_active: bool = True
    created_at: str
    source_correction_id: Optional[str] = None


class RuleListResponse(BaseModel):
    """Response model containing a list of learned rules."""
    rules: List[RuleResponse]
    total: int


class RuleToggleRequest(BaseModel):
    """Request payload to toggle active status of a rule."""
    is_active: bool


class RuleToggleResponse(BaseModel):
    """Response model after toggling a rule's active state."""
    rule_id: str
    is_active: bool


class RuleCreateRequest(BaseModel):
    """Request payload to manually define a structured reconciliation rule."""
    name: str = Field(..., min_length=3, max_length=120)
    description: Optional[str] = ""
    source_counterparty_pattern: Optional[str] = None
    reference_prefix: Optional[str] = None
    currency: Optional[str] = None
    max_amount_difference: Optional[Decimal] = None
    max_settlement_delay_days: Optional[int] = None
    target_action: str = Field("PREFER_CANDIDATE", description="Action when rule matches")
    resulting_outcome: str = Field("MATCHED", description="Outcome: MATCHED or EXCEPTION")
    resulting_exception_type: Optional[str] = None
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    is_active: bool = True
    run_id: Optional[str] = Field(None, description="Optional run context for audit logging")


class RuleValidationResponse(BaseModel):
    """Validation response for a proposed structured rule."""
    valid: bool
    summary: str
    errors: List[str] = Field(default_factory=list)



# ---------------------------------------------------------------------------
# Rerun & Rule Impact
# ---------------------------------------------------------------------------

class RerunRequest(BaseModel):
    """Request payload to rerun reconciliation on an existing run's records."""
    apply_rules: bool = Field(True, description="Whether to apply active learned rules during rerun")


class RerunResponse(BaseModel):
    """Response model after executing a rerun."""
    parent_run_id: str
    rerun_id: str
    status: str
    apply_rules: bool
    summary: RunMetricsResponse


class MetricSnapshot(BaseModel):
    """Snapshot of metrics for before/after comparison."""
    run_id: str
    match_rate: float
    value_weighted_match_rate: float
    matched_count: int
    exception_count: int
    unresolved_count: int
    total_reconciled_amount: str


class MetricDelta(BaseModel):
    """Delta between before and after reconciliation runs."""
    match_rate_improvement: float
    value_weighted_improvement: float
    resolved_exceptions: int
    reconciled_amount_change: str


class RuleImpactResponse(BaseModel):
    """Detailed before-and-after impact comparison of learned rules on a run."""
    run_id: str
    has_rerun: bool
    before: Optional[MetricSnapshot] = None
    after: Optional[MetricSnapshot] = None
    delta: Optional[MetricDelta] = None


# ---------------------------------------------------------------------------
# Grounded Q&A / RAG Schemas
# ---------------------------------------------------------------------------

class SourceAttributionResponse(BaseModel):
    """Attributed source document providing evidence for a Q&A answer."""
    document_type: str
    identifier: str
    title: str
    snippet: str
    run_id: Optional[str] = None
    relationship_id: Optional[str] = None
    rule_id: Optional[str] = None
    correction_id: Optional[str] = None


class QARequestPayload(BaseModel):
    """Request body for grounded Q&A queries."""
    question: str = Field(..., description="Natural language question about reconciliation runs or rules")
    run_id: Optional[str] = Field(None, description="Optional run ID to scope retrieval")
    max_sources: int = Field(5, description="Maximum number of grounded context documents to retrieve")


class QAResponsePayload(BaseModel):
    """Grounded answer with source citations."""
    question: str
    answer: str
    sources: List[SourceAttributionResponse] = Field(default_factory=list)
    run_id: Optional[str] = None
    has_sufficient_evidence: bool = True
    retrieval_latency_ms: float = 0.0
    generation_latency_ms: float = 0.0


class IndexRunResponse(BaseModel):
    """Response after indexing operational run entities into ChromaDB."""
    run_id: str
    documents_indexed: int
    status: str = "INDEXED"


class ErrorResponse(BaseModel):
    """Standard error response."""
    error: str
    detail: Optional[str] = None


