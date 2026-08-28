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

        # 1. Exception Classification for committed results with exception_type=None
        exception_tasks = []
        for result in engine_output.results:
            if result.outcome == ReconciliationOutcome.EXCEPTION and result.exception_type is None:
                # Filter out validation exceptions (E-04: settlement < transaction)
                if self._is_validation_exception(result, source_lookup, target_lookup):
                    continue
                exception_tasks.append(self._classify_exception(result, source_lookup, target_lookup))

        exception_results = await asyncio.gather(*exception_tasks) if exception_tasks else []

        classified_results: List[ReconciliationResult] = []
        failed_cases: List[FailedClassification] = []

        for item in exception_results:
            if isinstance(item, ReconciliationResult):
                classified_results.append(item)
            elif isinstance(item, FailedClassification):
                failed_cases.append(item)

        # 2. Candidate Selection for unresolved candidate pools
        candidate_tasks = []
        for candidate in engine_output.candidates:
            candidate_tasks.append(self._select_candidate(candidate, source_lookup, target_lookup))

        candidate_results = await asyncio.gather(*candidate_tasks) if candidate_tasks else []

        # 3. Global Commit Validation
        # Initialize globally committed sets from deterministic results
        globally_committed_sources = {sid for r in engine_output.results for sid in r.source_record_ids}
        globally_committed_targets = {tid for r in engine_output.results for tid in r.target_record_ids}

        # Process candidate selection results in deterministic order
        for item in candidate_results:
            if isinstance(item, ReconciliationResult):
                # Check for global collision
                source_conflicts = set(item.source_record_ids) & globally_committed_sources
                target_conflicts = set(item.target_record_ids) & globally_committed_targets

                if source_conflicts or target_conflicts:
                    conflicts = sorted(list(source_conflicts | target_conflicts))
                    logger.warning(
                        "Global participant collision on records %s for relationship %s",
                        conflicts, item.relationship_id
                    )
                    failed_cases.append(
                        FailedClassification(
                            source_record_ids=item.source_record_ids,
                            candidate_target_record_ids=item.target_record_ids,
                            case_type="CANDIDATE_SELECTION",
                            failure_reason=f"Global participant collision on record(s): {conflicts}",
                            attempts=1,
                        )
                    )
                else:
                    # Validated globally: commit and reserve participants
                    globally_committed_sources.update(item.source_record_ids)
                    globally_committed_targets.update(item.target_record_ids)
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
        
        anchor_id = "unknown"
        if evidence.candidate_options:
            if len(evidence.candidate_options[0].source_record_ids) == 1:
                anchor_id = evidence.candidate_options[0].source_record_ids[0]
            else:
                anchor_id = evidence.candidate_options[0].target_record_ids[0]

        for attempt in range(1, self._max_retries + 2):
            async with self._semaphore:
                try:
                    decision = await self._provider.select_candidate(case)
                    validated = self._validate_candidate_decision(decision, case, evidence)
                    return validated
                except _SafetyViolation as e:
                    logger.warning(
                        "Safety violation for candidate decision (anchor=%s, attempt=%d): %s", 
                        anchor_id,
                        attempt,
                        e
                    )
                    return FailedClassification(
                        source_record_ids=sorted(list({sid for opt in evidence.candidate_options for sid in opt.source_record_ids})),
                        candidate_target_record_ids=sorted(list({tid for opt in evidence.candidate_options for tid in opt.target_record_ids})),
                        case_type="CANDIDATE_SELECTION",
                        failure_reason=f"Safety violation: {e}",
                        attempts=attempt,
                    )
                except Exception as e:
                    logger.warning(
                        "Attempt %d failed for candidate (anchor=%s): %s",
                        attempt, anchor_id, e
                    )
                    if attempt > self._max_retries:
                        return FailedClassification(
                            source_record_ids=sorted(list({sid for opt in evidence.candidate_options for sid in opt.source_record_ids})),
                            candidate_target_record_ids=sorted(list({tid for opt in evidence.candidate_options for tid in opt.target_record_ids})),
                            case_type="CANDIDATE_SELECTION",
                            failure_reason=str(e),
                            attempts=attempt,
                        )

        return FailedClassification(
            source_record_ids=sorted(list({sid for opt in evidence.candidate_options for sid in opt.source_record_ids})),
            candidate_target_record_ids=sorted(list({tid for opt in evidence.candidate_options for tid in opt.target_record_ids})),
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
        """Build a ClassificationCase for candidate selection with enriched metadata."""
        all_src_ids = sorted(list({sid for opt in evidence.candidate_options for sid in opt.source_record_ids}))
        all_tgt_ids = sorted(list({tid for opt in evidence.candidate_options for tid in opt.target_record_ids}))

        src_records = [source_lookup[sid] for sid in all_src_ids if sid in source_lookup]
        tgt_records = [target_lookup[tid] for tid in all_tgt_ids if tid in target_lookup]

        # Build enriched metadata sections
        meta_lines = [
            f"EVIDENCE CONTEXT: {evidence.relationship_context}",
            "",
            "SOURCE RECORDS:",
        ]
        for r in src_records:
            meta_lines.append(f"- ID: {r.record_id}")
            meta_lines.append(f"  Amount: {r.amount} {r.currency}")
            meta_lines.append(f"  Transaction Date: {r.transaction_date}")
            meta_lines.append(f"  Settlement Date: {r.settlement_date}")
            if r.source_reference:
                meta_lines.append(f"  Reference: {r.source_reference}")
            if r.counterparty:
                meta_lines.append(f"  Counterparty: {r.counterparty}")
            if r.transaction_id and r.transaction_id != r.record_id:
                meta_lines.append(f"  Transaction ID: {r.transaction_id}")
            if r.fee_amount is not None:
                meta_lines.append(f"  Fee Amount: {r.fee_amount}")
            if r.gross_amount is not None:
                meta_lines.append(f"  Gross Amount: {r.gross_amount}")
            if r.net_amount is not None:
                meta_lines.append(f"  Net Amount: {r.net_amount}")
            meta_lines.append(f"  Type: {r.transaction_type}")
            meta_lines.append(f"  Status: {r.status}")

        meta_lines.append("")
        meta_lines.append("TARGET RECORDS:")
        for r in tgt_records:
            meta_lines.append(f"- ID: {r.record_id}")
            meta_lines.append(f"  Amount: {r.amount} {r.currency}")
            meta_lines.append(f"  Transaction Date: {r.transaction_date}")
            meta_lines.append(f"  Settlement Date: {r.settlement_date}")
            if r.source_reference:
                meta_lines.append(f"  Reference: {r.source_reference}")
            if r.counterparty:
                meta_lines.append(f"  Counterparty: {r.counterparty}")
            if r.transaction_id and r.transaction_id != r.record_id:
                meta_lines.append(f"  Transaction ID: {r.transaction_id}")
            if r.fee_amount is not None:
                meta_lines.append(f"  Fee Amount: {r.fee_amount}")
            if r.gross_amount is not None:
                meta_lines.append(f"  Gross Amount: {r.gross_amount}")
            if r.net_amount is not None:
                meta_lines.append(f"  Net Amount: {r.net_amount}")
            meta_lines.append(f"  Type: {r.transaction_type}")
            meta_lines.append(f"  Status: {r.status}")

        return ClassificationCase(
            case_type="CANDIDATE_SELECTION",
            source_record_ids=all_src_ids,
            committed_target_record_ids=[],
            candidate_options=evidence.candidate_options,
            committed_relationship_type=None,
            source_amounts=[r.amount for r in src_records],
            source_currencies=[r.currency for r in src_records],
            target_amounts=[r.amount for r in tgt_records],
            target_currencies=[r.currency for r in tgt_records],
            source_transaction_dates=[str(r.transaction_date) for r in src_records],
            target_settlement_dates=[str(r.settlement_date) for r in tgt_records],
            evidence_summary="\n".join(meta_lines),
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
        # 1. Validate candidate index bounds
        idx = decision.selected_candidate_index
        if idx is None:
            source_ids = sorted(list({sid for opt in evidence.candidate_options for sid in opt.source_record_ids}))
            target_ids = []
        else:
            if not (0 <= idx < len(evidence.candidate_options)):
                raise _SafetyViolation(f"Candidate index out of bounds: {idx}")
                
            selected_option = evidence.candidate_options[idx]
            source_ids = list(selected_option.source_record_ids)
            target_ids = list(selected_option.target_record_ids)

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

        # 3. Validate no N:M (Should be structurally impossible now but keep safety check)
        if len(source_ids) > 1 and len(target_ids) > 1:
            raise _SafetyViolation("N:M relationship not allowed")

        # 4. Validate reconciled amount
        try:
            reconciled_amount = Decimal(decision.reconciled_amount)
        except (InvalidOperation, ValueError):
            raise _SafetyViolation(
                f"Invalid reconciled_amount: {decision.reconciled_amount}"
            )

        # 4. Validate amount (if MATCHED)
        if decision.outcome == "MATCHED":
            selected_source_amounts = []
            for sid in source_ids:
                if sid in case.source_record_ids:
                    sidx = case.source_record_ids.index(sid)
                    selected_source_amounts.append(case.source_amounts[sidx])
            total_source_amount = sum(Decimal(str(amt)) for amt in selected_source_amounts)
            if reconciled_amount != total_source_amount:
                raise _SafetyViolation(
                    f"Reconciled amount {reconciled_amount} does not match "
                    f"source amount {total_source_amount}"
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
        elif len(target_ids) == 1 and len(source_ids) > 1:
            if relationship_type != RelationshipType.MANY_TO_ONE:
                raise _SafetyViolation(
                    f"Multiple sources + single target must use N:1, got {relationship_type.value}"
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
