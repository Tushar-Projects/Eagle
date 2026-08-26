"""Eagle domain models.

Re-exports for convenient downstream imports.
"""

from eagle.models.canonical import CanonicalRecord
from eagle.models.enums import (
    ExceptionType,
    ReconciliationOutcome,
    RelationshipType,
    Severity,
)
from eagle.models.evidence import CandidateRelationshipEvidence, EngineOutput
from eagle.models.ground_truth import GroundTruthDataset, GroundTruthRelationship
from eagle.models.reconciliation import ReconciliationResult

__all__ = [
    "CandidateRelationshipEvidence",
    "CanonicalRecord",
    "EngineOutput",
    "ExceptionType",
    "GroundTruthDataset",
    "GroundTruthRelationship",
    "ReconciliationOutcome",
    "ReconciliationResult",
    "RelationshipType",
    "Severity",
]
