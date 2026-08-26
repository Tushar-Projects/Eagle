"""AI Exception & Ambiguity Classifier.

Consumes unresolved evidence from the deterministic reconciliation engine
(EngineOutput) and produces final committed ReconciliationResult objects
where semantic reasoning is genuinely required.

The classifier resolves two categories of work:
1. Exception Classification — committed relationship, unresolved exception_type.
2. Candidate Selection — unresolved candidate pool, no committed relationship.

Safety boundaries:
- The AI MUST NOT fabricate record IDs.
- The AI MUST NOT override deterministic topology or financial facts.
- The AI MUST NOT access ground_truth.json or benchmark case IDs.
- Relationship IDs are always generated deterministically by the application.
"""

import asyncio
import logging
from decimal import Decimal, InvalidOperation
from typing import List

from eagle.agents.provider import LLMProvider
from eagle.models.ai_contracts import (
    CandidateSelectionDecision,
    ClassificationCase,
    ClassifierOutput,
    ExceptionClassificationDecision,
    FailedClassification,
)
from eagle.models.canonical import CanonicalRecord
from eagle.models.enums import (
    ExceptionType,
    ReconciliationOutcome,
    RelationshipType,
    Severity,
)
from eagle.models.evidence import CandidateRelationshipEvidence, EngineOutput
from eagle.models.reconciliation import ReconciliationResult
from eagle.reconciliation.utils import generate_relationship_id

logger = logging.getLogger(__name__)


class AIExceptionClassifier:
    """Consumes EngineOutput and produces final ReconciliationResults
    for unresolved cases via LLM-based semantic reasoning."""

    def __init__(self, provider: LLMProvider, max_retries: int = 2, max_concurrency: int = 5):
        self._provider = provider
        self._max_retries = max_retries
        self._semaphore = asyncio.Semaphore(max_concurrency)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def classify_all(
        self,
        engine_output: EngineOutput,
        source_records: List[CanonicalRecord],
        target_records: List[CanonicalRecord],
    ) -> ClassifierOutput:
        """Async entry point. Classifies all unresolved cases."""
        source_lookup = {r.record_id: r for r in source_records}
        target_lookup = {r.record_id: r for r in target_records}

        tasks = []

        # 1. Exception Classification for committed results with exception_type=None
        for result in engine_output.results:
            if result.outcome == ReconciliationOutcome.EXCEPTION and result.exception_type is None:
                # Filter out validation exceptions (E-04: settlement < transaction)
                if self._is_validation_exception(result, source_lookup, target_lookup):
                    continue
                tasks.append(self._classify_exception(result, source_lookup, target_lookup))

        # 2. Candidate Selection for unresolved candidate pools
        for candidate in engine_output.candidates:
            tasks.append(self._select_candidate(candidate, source_lookup, target_lookup))

        task_results = await asyncio.gather(*tasks)

        classified_results: List[ReconciliationResult] = []
        failed_cases: List[FailedClassification] = []

        for item in task_results:
            if isinstance(item, ReconciliationResult):
                classified_results.append(item)
            elif isinstance(item, FailedClassification):
                failed_cases.append(item)

        return ClassifierOutput(
            classified_results=classified_results,
            failed_cases=failed_cases,
        )

    def classify_all_sync(
        self,
        engine_output: EngineOutput,
        source_records: List[CanonicalRecord],
        target_records: List[CanonicalRecord],
    ) -> ClassifierOutput:
        """Synchronous wrapper for classify_all.

        Uses asyncio.run() if no event loop is running.
        Raises RuntimeError if called from within a running event loop.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            raise RuntimeError(
                "classify_all_sync() cannot be called from within a running "
                "event loop. Use 'await classify_all(...)' instead."
            )

        return asyncio.run(
            self.classify_all(engine_output, source_records, target_records)
        )

    # ------------------------------------------------------------------
    # Validation exception detection
    # ------------------------------------------------------------------

    @staticmethod
    def _is_validation_exception(
        result: ReconciliationResult,
        source_lookup: dict[str, CanonicalRecord],
        target_lookup: dict[str, CanonicalRecord],
    ) -> bool:
        """Detect validation exceptions (settlement_date < transaction_date).

        These are NOT part of the AI exception taxonomy and must be skipped.
        """
        for sid in result.source_record_ids:
            src = source_lookup.get(sid)
            if src is None:
                continue
            for tid in result.target_record_ids:
                tgt = target_lookup.get(tid)
                if tgt is None:
                    continue
                if tgt.settlement_date < src.transaction_date:
                    return True
        return False

    # ------------------------------------------------------------------
    # Exception Classification
    # ------------------------------------------------------------------

    async def _classify_exception(
        self,
        result: ReconciliationResult,
        source_lookup: dict[str, CanonicalRecord],
        target_lookup: dict[str, CanonicalRecord],
    ) -> ReconciliationResult | FailedClassification:
        """Classify a committed relationship with unresolved exception_type."""
        case = self._build_exception_case(result, source_lookup, target_lookup)

        for attempt in range(1, self._max_retries + 2):  # +2 for initial attempt + retries
            async with self._semaphore:
                try:
                    decision = await self._provider.classify_exception(case)
                    validated = self._validate_exception_decision(decision, result)
                    return validated
                except _SafetyViolation as e:
                    # Safety violations are never retried
                    logger.warning(
                        "Safety violation for %s: %s", result.source_record_ids, e
                    )
                    return FailedClassification(
                        source_record_ids=result.source_record_ids,
                        candidate_target_record_ids=result.target_record_ids,
                        case_type="EXCEPTION_CLASSIFICATION",
                        failure_reason=f"Safety violation: {e}",
                        attempts=attempt,
                    )
                except Exception as e:
                    logger.warning(
                        "Attempt %d failed for %s: %s",
                        attempt, result.source_record_ids, e,
                    )
                    if attempt > self._max_retries:
                        return FailedClassification(
                            source_record_ids=result.source_record_ids,
                            candidate_target_record_ids=result.target_record_ids,
                            case_type="EXCEPTION_CLASSIFICATION",
                            failure_reason=str(e),
                            attempts=attempt,
                        )

        # Should not reach here, but safety fallback
        return FailedClassification(
            source_record_ids=result.source_record_ids,
            candidate_target_record_ids=result.target_record_ids,
            case_type="EXCEPTION_CLASSIFICATION",
            failure_reason="Max retries exhausted",
            attempts=self._max_retries + 1,
        )

    # ------------------------------------------------------------------
    # Candidate Selection
    # ------------------------------------------------------------------

    async def _select_candidate(
        self,
        evidence: CandidateRelationshipEvidence,
        source_lookup: dict[str, CanonicalRecord],
        target_lookup: dict[str, CanonicalRecord],
    ) -> ReconciliationResult | FailedClassification:
        """Resolve an ambiguous candidate pool."""
        case = self._build_candidate_case(evidence, source_lookup, target_lookup)

        for attempt in range(1, self._max_retries + 2):
            async with self._semaphore:
                try:
                    decision = await self._provider.select_candidate(case)
                    validated = self._validate_candidate_decision(decision, case, evidence)
                    return validated
                except _SafetyViolation as e:
                    logger.warning(
                        "Safety violation for %s: %s", evidence.source_record_ids, e
                    )
                    return FailedClassification(
                        source_record_ids=evidence.source_record_ids,
                        candidate_target_record_ids=evidence.candidate_target_record_ids,
                        case_type="CANDIDATE_SELECTION",
                        failure_reason=f"Safety violation: {e}",
                        attempts=attempt,
                    )
                except Exception as e:
                    logger.warning(
                        "Attempt %d failed for %s: %s",
                        attempt, evidence.source_record_ids, e,
                    )
                    if attempt > self._max_retries:
                        return FailedClassification(
                            source_record_ids=evidence.source_record_ids,
                            candidate_target_record_ids=evidence.candidate_target_record_ids,
                            case_type="CANDIDATE_SELECTION",
                            failure_reason=str(e),
                            attempts=attempt,
                        )

        return FailedClassification(
            source_record_ids=evidence.source_record_ids,
            candidate_target_record_ids=evidence.candidate_target_record_ids,
            case_type="CANDIDATE_SELECTION",
            failure_reason="Max retries exhausted",
            attempts=self._max_retries + 1,
        )

    # ------------------------------------------------------------------
    # Case Builders
    # ------------------------------------------------------------------

    @staticmethod
    def _build_exception_case(
        result: ReconciliationResult,
        source_lookup: dict[str, CanonicalRecord],
        target_lookup: dict[str, CanonicalRecord],
    ) -> ClassificationCase:
        """Build a ClassificationCase for exception classification."""
        src_records = [source_lookup[sid] for sid in result.source_record_ids if sid in source_lookup]
        tgt_records = [target_lookup[tid] for tid in result.target_record_ids if tid in target_lookup]

        # Build evidence summary
        evidence_parts = []
        if src_records and tgt_records:
            src_amt = src_records[0].amount
            tgt_amt = sum(t.amount for t in tgt_records)
            if src_amt != tgt_amt:
                evidence_parts.append(f"Amount difference: source={src_amt}, target_total={tgt_amt}")
            src_curr = src_records[0].currency
            tgt_currs = {t.currency for t in tgt_records}
            if len(tgt_currs) == 1 and src_curr != next(iter(tgt_currs)):
                evidence_parts.append(f"Currency conflict: source={src_curr}, target={next(iter(tgt_currs))}")
            if len(tgt_records) > 1:
                evidence_parts.append(f"Multiple targets: {len(tgt_records)} records")

        return ClassificationCase(
            case_type="EXCEPTION_CLASSIFICATION",
            source_record_ids=result.source_record_ids,
            committed_target_record_ids=result.target_record_ids,
            candidate_target_record_ids=[],
            committed_relationship_type=result.relationship_type.value,
            source_amounts=[r.amount for r in src_records],
            source_currencies=[r.currency for r in src_records],
            target_amounts=[r.amount for r in tgt_records],
            target_currencies=[r.currency for r in tgt_records],
            source_transaction_dates=[str(r.transaction_date) for r in src_records],
            target_settlement_dates=[str(r.settlement_date) for r in tgt_records],
            evidence_summary="; ".join(evidence_parts) if evidence_parts else "No specific evidence flags",
        )

    @staticmethod
    def _build_candidate_case(
        evidence: CandidateRelationshipEvidence,
        source_lookup: dict[str, CanonicalRecord],
        target_lookup: dict[str, CanonicalRecord],
    ) -> ClassificationCase:
        """Build a ClassificationCase for candidate selection."""
        src_records = [source_lookup[sid] for sid in evidence.source_record_ids if sid in source_lookup]
        tgt_records = [target_lookup[tid] for tid in evidence.candidate_target_record_ids if tid in target_lookup]

        return ClassificationCase(
            case_type="CANDIDATE_SELECTION",
            source_record_ids=evidence.source_record_ids,
            committed_target_record_ids=[],
            candidate_target_record_ids=evidence.candidate_target_record_ids,
            committed_relationship_type=None,
            source_amounts=[r.amount for r in src_records],
            source_currencies=[r.currency for r in src_records],
            target_amounts=[r.amount for r in tgt_records],
            target_currencies=[r.currency for r in tgt_records],
            source_transaction_dates=[str(r.transaction_date) for r in src_records],
            target_settlement_dates=[str(r.settlement_date) for r in tgt_records],
            evidence_summary=evidence.relationship_context,
        )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_exception_decision(
        decision: ExceptionClassificationDecision,
        original: ReconciliationResult,
    ) -> ReconciliationResult:
        """Validate and apply an exception classification decision.

        Preserves all committed fields from the deterministic engine.
        Only exception_type, severity, flag_for_review may change.
        """
        # Validate enum values
        exception_type = None
        if decision.exception_type is not None:
            try:
                exception_type = ExceptionType(decision.exception_type)
            except ValueError:
                raise _SafetyViolation(
                    f"Invalid exception_type: {decision.exception_type}"
                )

        severity = None
        if decision.severity is not None:
            try:
                severity = Severity(decision.severity)
            except ValueError:
                raise _SafetyViolation(f"Invalid severity: {decision.severity}")

        # Build result preserving ALL committed fields from the engine
        return ReconciliationResult(
            relationship_id=original.relationship_id,
            relationship_type=original.relationship_type,
            source_record_ids=original.source_record_ids,
            target_record_ids=original.target_record_ids,
            outcome=original.outcome,
            exception_type=exception_type,
            severity=severity,
            flag_for_review=decision.flag_for_review,
            reconciled_amount=original.reconciled_amount,
        )

    @staticmethod
    def _validate_candidate_decision(
        decision: CandidateSelectionDecision,
        case: ClassificationCase,
        evidence: CandidateRelationshipEvidence,
    ) -> ReconciliationResult:
        """Validate a candidate selection decision.

        Enforces:
        - selected targets must be subset of candidate pool
        - valid enum values
        - no N:M relationships
        - reconciled amount must equal source amount
        - no hallucinated IDs
        """
        # 1. Validate selected target IDs are subset of candidates
        allowed_targets = set(case.candidate_target_record_ids)
        selected = set(decision.selected_target_record_ids)
        if not selected.issubset(allowed_targets):
            fabricated = selected - allowed_targets
            raise _SafetyViolation(
                f"AI fabricated target IDs: {fabricated}"
            )

        # 2. Validate enum values
        try:
            relationship_type = RelationshipType(decision.relationship_type)
        except ValueError:
            raise _SafetyViolation(
                f"Invalid relationship_type: {decision.relationship_type}"
            )

        try:
            outcome = ReconciliationOutcome(decision.outcome)
        except ValueError:
            raise _SafetyViolation(f"Invalid outcome: {decision.outcome}")

        exception_type = None
        if decision.exception_type is not None:
            try:
                exception_type = ExceptionType(decision.exception_type)
            except ValueError:
                raise _SafetyViolation(
                    f"Invalid exception_type: {decision.exception_type}"
                )

        severity = None
        if decision.severity is not None:
            try:
                severity = Severity(decision.severity)
            except ValueError:
                raise _SafetyViolation(f"Invalid severity: {decision.severity}")

        # 3. Validate no N:M
        source_ids = list(evidence.source_record_ids)
        target_ids = list(decision.selected_target_record_ids)
        if len(source_ids) > 1 and len(target_ids) > 1:
            raise _SafetyViolation("N:M relationship not allowed")

        # 4. Validate reconciled amount
        try:
            reconciled_amount = Decimal(decision.reconciled_amount)
        except (InvalidOperation, ValueError):
            raise _SafetyViolation(
                f"Invalid reconciled_amount: {decision.reconciled_amount}"
            )

        # reconciled_amount must equal source amount
        if case.source_amounts:
            expected_amount = case.source_amounts[0]
            if reconciled_amount != expected_amount:
                raise _SafetyViolation(
                    f"Reconciled amount {reconciled_amount} does not match "
                    f"source amount {expected_amount}"
                )

        # 5. Validate topology consistency
        if len(target_ids) == 0:
            # Selecting no target (e.g., POSSIBLE_DUPLICATE) must be 1:1
            if relationship_type != RelationshipType.ONE_TO_ONE:
                raise _SafetyViolation(
                    f"Zero-target selection must use 1:1, got {relationship_type.value}"
                )
        elif len(target_ids) == 1 and len(source_ids) == 1:
            if relationship_type != RelationshipType.ONE_TO_ONE:
                raise _SafetyViolation(
                    f"Single source + single target must use 1:1, got {relationship_type.value}"
                )
        elif len(target_ids) > 1 and len(source_ids) == 1:
            if relationship_type != RelationshipType.ONE_TO_MANY:
                raise _SafetyViolation(
                    f"Single source + multiple targets must use 1:N, got {relationship_type.value}"
                )

        # 6. Generate relationship ID deterministically
        rel_id = generate_relationship_id(source_ids, target_ids)

        return ReconciliationResult(
            relationship_id=rel_id,
            relationship_type=relationship_type,
            source_record_ids=source_ids,
            target_record_ids=target_ids,
            outcome=outcome,
            exception_type=exception_type,
            severity=severity,
            flag_for_review=decision.flag_for_review,
            reconciled_amount=reconciled_amount,
        )


class _SafetyViolation(Exception):
    """Raised when AI output violates a deterministic safety boundary.

    Safety violations are never retried.
    """
    pass
