"""Eagle evaluation package."""

from eagle.evaluation.models import (
    EvaluationReport,
    RelationshipMetrics,
    ClassificationMetrics,
    AmountMetrics,
    CandidateMetrics,
    AIImprovementMetrics,
    ErrorDiagnostic,
    PipelineOutput,
    ComparisonMetrics
)
from eagle.evaluation.runner import run_synthetic_benchmark, run_deterministic_only
from eagle.evaluation.report import to_summary

__all__ = [
    "EvaluationReport",
    "RelationshipMetrics",
    "ClassificationMetrics",
    "AmountMetrics",
    "CandidateMetrics",
    "AIImprovementMetrics",
    "ErrorDiagnostic",
    "PipelineOutput",
    "ComparisonMetrics",
    "run_synthetic_benchmark",
    "run_deterministic_only",
    "to_summary",
]
