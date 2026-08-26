"""Candidate evidence models for the reconciliation engine.

These models represent unresolved candidate pools (evidence) that are passed to the 
future AI layer for semantic resolution, explicitly keeping them separate from 
committed reconciliation results.
"""

from pydantic import BaseModel

from eagle.models.reconciliation import ReconciliationResult


class CandidateRelationshipEvidence(BaseModel):
    """An unresolved candidate pool of evidence.

    This represents plausible candidates (e.g., a single source and multiple 
    compatible targets) where the deterministic engine lacks sufficient evidence 
    to commit to a final structural relationship or select a specific counterpart.

    Note: `candidate_target_record_ids` are PLAUSIBLE CANDIDATES, not confirmed targets.
    """

    source_record_ids: list[str]
    candidate_target_record_ids: list[str]
    relationship_context: str
    amount_evidence: str = ""
    date_evidence: str = ""
    currency_evidence: str = ""
    reference_evidence: str = ""


class EngineOutput(BaseModel):
    """The unified output container for the deterministic reconciliation engine.

    Maintains a strict architectural boundary between:
    - results: Committed structural relationships
    - candidates: Unresolved candidate pools intended for the AI classifier
    """

    results: list[ReconciliationResult]
    candidates: list[CandidateRelationshipEvidence]
