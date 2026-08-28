"""Evaluation layer data models."""

from decimal import Decimal
from pydantic import BaseModel

from eagle.models.reconciliation import ReconciliationResult
from eagle.models.evidence import CandidateRelationshipEvidence
from eagle.models.ai_contracts import FailedClassification


class RelationshipMetrics(BaseModel):
    total_ground_truth: int
    total_predictions: int
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float


class ClassificationMetrics(BaseModel):
    total_aligned: int
    outcome_correct: int
    outcome_accuracy: float
    exception_type_correct: int
    exception_type_accuracy: float
    relationship_type_correct: int
    relationship_type_accuracy: float
    exception_type_breakdown: dict[str, dict[str, int]]


class AmountMetrics(BaseModel):
    total_aligned: int
    exact_match_count: int
    exact_match_accuracy: float
    within_tolerance_count: int
    within_tolerance_accuracy: float
    mean_absolute_error: Decimal
    amount_errors: list[dict]


class CandidateMetrics(BaseModel):
    total_candidate_pools: int
    resolved_candidates: int
    failed_candidates: int
    unresolved_candidates: int
    correct_selections: int
    incorrect_selections: int


class AIImprovementMetrics(BaseModel):
    relationships_resolved_by_ai: int
    exceptions_classified_by_ai: int
    precision_delta: float
    recall_delta: float
    f1_delta: float
    exception_accuracy_delta: float


class ErrorDiagnostic(BaseModel):
    error_type: str
    gt_relationship_id: str | None
    source_record_ids: list[str]
    target_record_ids: list[str]
    expected: dict
    predicted: dict | None
    detail: str


class EvaluationReport(BaseModel):
    relationship_metrics: RelationshipMetrics
    classification_metrics: ClassificationMetrics
    amount_metrics: AmountMetrics
    candidate_metrics: CandidateMetrics
    deterministic_metrics: RelationshipMetrics
    final_metrics: RelationshipMetrics
    ai_improvement: AIImprovementMetrics
    errors: list[ErrorDiagnostic]
    severity_distribution: dict[str, int]
    flag_for_review_count: int


class PipelineOutput(BaseModel):
    """Combined output from deterministic engine + AI classifier."""
    predictions: list[ReconciliationResult]
    failed_classifications: list[FailedClassification]
    unresolved_candidates: list[CandidateRelationshipEvidence]


class ComparisonMetrics(BaseModel):
    deterministic_only: RelationshipMetrics
    final: RelationshipMetrics
    ai_improvement: AIImprovementMetrics
