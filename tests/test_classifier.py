"""Tests for the AI Exception & Ambiguity Classifier (Chunk 4).

All tests use MockProvider. No live Gemini or Claude API calls.
"""

import asyncio
import datetime
from decimal import Decimal

import pytest

from eagle.agents._mock import MockProvider
from eagle.agents.classifier import AIExceptionClassifier
from eagle.models.ai_contracts import (
    CandidateSelectionDecision,
    ClassificationCase,
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_record(
    record_id: str,
    amount: str = "5000.00",
    currency: str = "INR",
    txn_date: str = "2025-01-15",
    stl_date: str = "2025-01-17",
    source: str = "GATEWAY",
) -> CanonicalRecord:
    return CanonicalRecord(
        record_id=record_id,
        transaction_id=record_id,
        source=source,
        source_reference="",
        amount=Decimal(amount),
        currency=currency,
        transaction_date=datetime.date.fromisoformat(txn_date),
        settlement_date=datetime.date.fromisoformat(stl_date),
        counterparty="",
        status="SUCCESS",
        transaction_type="PAYMENT" if source == "GATEWAY" else "CREDIT",
    )


def _make_committed_result(
    source_ids: list[str],
    target_ids: list[str],
    rel_type: str = "1:1",
    outcome: str = "EXCEPTION",
    exception_type: str | None = None,
    amount: str = "5000.00",
) -> ReconciliationResult:
    return ReconciliationResult(
        relationship_id=generate_relationship_id(source_ids, target_ids),
        relationship_type=RelationshipType(rel_type),
        source_record_ids=source_ids,
        target_record_ids=target_ids,
        outcome=ReconciliationOutcome(outcome),
        exception_type=ExceptionType(exception_type) if exception_type else None,
        severity=Severity.HIGH,
        flag_for_review=True,
        reconciled_amount=Decimal(amount),
    )


def _run_sync(coro):
    """Run a coroutine synchronously."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# 1. E-04 never sent to AI
# ---------------------------------------------------------------------------


def test_e04_never_sent_to_ai():
    """E-04 validation exception (settlement < transaction) must NOT be sent to AI."""
    # Settlement date (Jan 10) precedes transaction date (Jan 15) → validation exception
    src = _make_record("GTW-E04", txn_date="2025-01-15", stl_date="2025-01-15")
    tgt = _make_record("BANK-E04", txn_date="2025-01-10", stl_date="2025-01-10", source="BANK")

    result = _make_committed_result(["GTW-E04"], ["BANK-E04"])
    engine_output = EngineOutput(results=[result], candidates=[])

    provider = MockProvider()
    classifier = AIExceptionClassifier(provider=provider)

    output = classifier.classify_all_sync(engine_output, [src], [tgt])

    # Provider should never be called for E-04
    assert len(provider.exception_calls) == 0
    assert len(provider.candidate_calls) == 0
    assert len(output.classified_results) == 0
    assert len(output.failed_cases) == 0


# ---------------------------------------------------------------------------
# 2. Committed participant IDs preserved
# ---------------------------------------------------------------------------


def test_exception_committed_ids_preserved():
    """For exception classification, source/target IDs must be preserved exactly."""
    src = _make_record("GTW-D05", currency="INR")
    tgt = _make_record("BANK-D05", currency="USD", source="BANK")

    result = _make_committed_result(["GTW-D05"], ["BANK-D05"])

    def handler(case):
        return ExceptionClassificationDecision(
            exception_type="CURRENCY_MISMATCH",
            severity="HIGH",
            flag_for_review=True,
            reasoning="Currency mismatch",
            confidence=0.9,
        )

    provider = MockProvider(exception_handler=handler)
    classifier = AIExceptionClassifier(provider=provider)
    engine_output = EngineOutput(results=[result], candidates=[])

    output = classifier.classify_all_sync(engine_output, [src], [tgt])

    assert len(output.classified_results) == 1
    classified = output.classified_results[0]
    assert classified.source_record_ids == ["GTW-D05"]
    assert classified.target_record_ids == ["BANK-D05"]
    assert classified.relationship_type == RelationshipType.ONE_TO_ONE
    assert classified.relationship_id == result.relationship_id
    assert classified.reconciled_amount == result.reconciled_amount


# ---------------------------------------------------------------------------
# 3. Fabricated source ID rejected
# ---------------------------------------------------------------------------


def test_exception_fabricated_source_id_rejected():
    """AI cannot fabricate source IDs — but for exception classification,
    source IDs are not even part of the AI decision, so this tests the
    candidate selection path where fabrication is possible."""
    src = _make_record("GTW-X")
    tgt1 = _make_record("BANK-Y", source="BANK")

    evidence = CandidateRelationshipEvidence(
        source_record_ids=["GTW-X"],
        candidate_target_record_ids=["BANK-Y"],
        relationship_context="Test",
    )

    def handler(case):
        return CandidateSelectionDecision(
            selected_target_record_ids=["BANK-FABRICATED"],  # Fabricated!
            relationship_type="1:1",
            outcome="MATCHED",
            exception_type=None,
            severity=None,
            flag_for_review=False,
            reconciled_amount="5000.00",
            reasoning="test",
            confidence=0.9,
        )

    provider = MockProvider(candidate_handler=handler)
    classifier = AIExceptionClassifier(provider=provider, max_retries=0)
    engine_output = EngineOutput(results=[], candidates=[evidence])

    output = classifier.classify_all_sync(engine_output, [src], [tgt1])

    assert len(output.classified_results) == 0
    assert len(output.failed_cases) == 1
    assert "fabricated" in output.failed_cases[0].failure_reason.lower() or "Safety" in output.failed_cases[0].failure_reason


# ---------------------------------------------------------------------------
# 4. Fabricated target ID rejected
# ---------------------------------------------------------------------------


def test_exception_fabricated_target_id_rejected():
    """AI returns a target ID not in the candidate pool → rejected."""
    src = _make_record("GTW-X")
    tgt1 = _make_record("BANK-Y", source="BANK")

    evidence = CandidateRelationshipEvidence(
        source_record_ids=["GTW-X"],
        candidate_target_record_ids=["BANK-Y"],
        relationship_context="Test",
    )

    def handler(case):
        return CandidateSelectionDecision(
            selected_target_record_ids=["BANK-Z"],  # Not in candidates!
            relationship_type="1:1",
            outcome="MATCHED",
            exception_type=None,
            severity=None,
            flag_for_review=False,
            reconciled_amount="5000.00",
            reasoning="test",
            confidence=0.9,
        )

    provider = MockProvider(candidate_handler=handler)
    classifier = AIExceptionClassifier(provider=provider, max_retries=0)
    engine_output = EngineOutput(results=[], candidates=[evidence])

    output = classifier.classify_all_sync(engine_output, [src], [tgt1])

    assert len(output.classified_results) == 0
    assert len(output.failed_cases) == 1


# ---------------------------------------------------------------------------
# 5. Candidate IDs restricted to supplied evidence
# ---------------------------------------------------------------------------


def test_candidate_ids_restricted_to_evidence():
    """Selected target must come from the candidate pool."""
    src = _make_record("GTW-E03")
    tgt1 = _make_record("BANK-E03", source="BANK")
    tgt2 = _make_record("BANK-D03", source="BANK")

    evidence = CandidateRelationshipEvidence(
        source_record_ids=["GTW-E03"],
        candidate_target_record_ids=["BANK-E03", "BANK-D03"],
        relationship_context="Ambiguous pool",
    )

    def handler(case):
        return CandidateSelectionDecision(
            selected_target_record_ids=["BANK-E03"],  # Valid selection
            relationship_type="1:1",
            outcome="MATCHED",
            exception_type=None,
            severity=None,
            flag_for_review=False,
            reconciled_amount="5000.00",
            reasoning="Selected based on date proximity",
            confidence=0.8,
        )

    provider = MockProvider(candidate_handler=handler)
    classifier = AIExceptionClassifier(provider=provider)
    engine_output = EngineOutput(results=[], candidates=[evidence])

    output = classifier.classify_all_sync(engine_output, [src], [tgt1, tgt2])

    assert len(output.classified_results) == 1
    assert output.classified_results[0].target_record_ids == ["BANK-E03"]


# ---------------------------------------------------------------------------
# 6. 1:N not fabricated from a 1:1 candidate pool
# ---------------------------------------------------------------------------


def test_candidate_1n_not_fabricated_from_1_1_pool():
    """AI selects both candidates as 1:N from a 1:1 ambiguity → rejected.
    Selecting 2 targets as 1:N must use the ONE_TO_MANY type but the pool
    is ambiguous 1:1 candidates, so validation rejects topology if AI claims 1:1."""
    src = _make_record("GTW-E03")
    tgt1 = _make_record("BANK-E03", source="BANK")
    tgt2 = _make_record("BANK-D03", source="BANK")

    evidence = CandidateRelationshipEvidence(
        source_record_ids=["GTW-E03"],
        candidate_target_record_ids=["BANK-E03", "BANK-D03"],
        relationship_context="Ambiguous pool",
    )

    def handler(case):
        return CandidateSelectionDecision(
            selected_target_record_ids=["BANK-E03", "BANK-D03"],  # Both!
            relationship_type="1:1",  # Can't be 1:1 with two targets
            outcome="MATCHED",
            exception_type=None,
            severity=None,
            flag_for_review=False,
            reconciled_amount="5000.00",
            reasoning="test",
            confidence=0.9,
        )

    provider = MockProvider(candidate_handler=handler)
    classifier = AIExceptionClassifier(provider=provider, max_retries=0)
    engine_output = EngineOutput(results=[], candidates=[evidence])

    output = classifier.classify_all_sync(engine_output, [src], [tgt1, tgt2])

    assert len(output.classified_results) == 0
    assert len(output.failed_cases) == 1


# ---------------------------------------------------------------------------
# 7. N:M rejected
# ---------------------------------------------------------------------------


def test_n_to_m_rejected():
    """AI returns >1 source AND >1 target → rejected."""
    src1 = _make_record("GTW-X1")
    src2 = _make_record("GTW-X2")
    tgt1 = _make_record("BANK-Y1", source="BANK")
    tgt2 = _make_record("BANK-Y2", source="BANK")

    evidence = CandidateRelationshipEvidence(
        source_record_ids=["GTW-X1", "GTW-X2"],
        candidate_target_record_ids=["BANK-Y1", "BANK-Y2"],
        relationship_context="Test",
    )

    def handler(case):
        return CandidateSelectionDecision(
            selected_target_record_ids=["BANK-Y1", "BANK-Y2"],
            relationship_type="1:N",  # Invalid for N:M
            outcome="MATCHED",
            exception_type=None,
            severity=None,
            flag_for_review=False,
            reconciled_amount="5000.00",
            reasoning="test",
            confidence=0.9,
        )

    provider = MockProvider(candidate_handler=handler)
    classifier = AIExceptionClassifier(provider=provider, max_retries=0)
    engine_output = EngineOutput(results=[], candidates=[evidence])

    output = classifier.classify_all_sync(engine_output, [src1, src2], [tgt1, tgt2])

    assert len(output.classified_results) == 0
    assert len(output.failed_cases) == 1
    assert "N:M" in output.failed_cases[0].failure_reason


# ---------------------------------------------------------------------------
# 8. Topology preserved for exception classification (E-06)
# ---------------------------------------------------------------------------


def test_topology_preserved_for_exception():
    """AI cannot change committed 1:N to 1:1 for exception classification."""
    src = _make_record("GTW-E06", amount="10000.00", txn_date="2025-03-10", stl_date="2025-03-10")
    tgt1 = _make_record("BANK-E06-1", amount="6000.00", txn_date="2025-03-12", stl_date="2025-03-12", source="BANK")
    tgt2 = _make_record("BANK-E06-2", amount="2500.00", txn_date="2025-03-13", stl_date="2025-03-13", source="BANK")

    result = _make_committed_result(
        ["GTW-E06"], ["BANK-E06-1", "BANK-E06-2"],
        rel_type="1:N", amount="10000.00",
    )
    engine_output = EngineOutput(results=[result], candidates=[])

    def handler(case):
        return ExceptionClassificationDecision(
            exception_type="SPLIT_SETTLEMENT",
            severity="HIGH",
            flag_for_review=True,
            reasoning="Split settlement with shortfall",
            confidence=0.9,
        )

    provider = MockProvider(exception_handler=handler)
    classifier = AIExceptionClassifier(provider=provider)

    output = classifier.classify_all_sync(engine_output, [src], [tgt1, tgt2])

    assert len(output.classified_results) == 1
    classified = output.classified_results[0]
    # Topology must be preserved as 1:N
    assert classified.relationship_type == RelationshipType.ONE_TO_MANY
    assert classified.source_record_ids == ["GTW-E06"]
    assert set(classified.target_record_ids) == {"BANK-E06-1", "BANK-E06-2"}
    assert classified.exception_type == ExceptionType.SPLIT_SETTLEMENT


# ---------------------------------------------------------------------------
# 9. Invalid reconciled amount rejected
# ---------------------------------------------------------------------------


def test_invalid_reconciled_amount_rejected():
    """AI returns a reconciled amount that doesn't match source → rejected."""
    src = _make_record("GTW-X", amount="5000.00")
    tgt = _make_record("BANK-Y", source="BANK")

    evidence = CandidateRelationshipEvidence(
        source_record_ids=["GTW-X"],
        candidate_target_record_ids=["BANK-Y"],
        relationship_context="Test",
    )

    def handler(case):
        return CandidateSelectionDecision(
            selected_target_record_ids=["BANK-Y"],
            relationship_type="1:1",
            outcome="MATCHED",
            exception_type=None,
            severity=None,
            flag_for_review=False,
            reconciled_amount="9999.99",  # Wrong amount!
            reasoning="test",
            confidence=0.9,
        )

    provider = MockProvider(candidate_handler=handler)
    classifier = AIExceptionClassifier(provider=provider, max_retries=0)
    engine_output = EngineOutput(results=[], candidates=[evidence])

    output = classifier.classify_all_sync(engine_output, [src], [tgt])

    assert len(output.classified_results) == 0
    assert len(output.failed_cases) == 1
    assert "amount" in output.failed_cases[0].failure_reason.lower()


# ---------------------------------------------------------------------------
# 10. Deterministic relationship ID reused
# ---------------------------------------------------------------------------


def test_relationship_id_deterministic():
    """AI results use the shared SHA-256 relationship ID function."""
    src = _make_record("GTW-E03")
    tgt = _make_record("BANK-E03", source="BANK")

    evidence = CandidateRelationshipEvidence(
        source_record_ids=["GTW-E03"],
        candidate_target_record_ids=["BANK-E03"],
        relationship_context="Test",
    )

    def handler(case):
        return CandidateSelectionDecision(
            selected_target_record_ids=["BANK-E03"],
            relationship_type="1:1",
            outcome="MATCHED",
            exception_type=None,
            severity=None,
            flag_for_review=False,
            reconciled_amount="5000.00",
            reasoning="test",
            confidence=0.9,
        )

    provider = MockProvider(candidate_handler=handler)
    classifier = AIExceptionClassifier(provider=provider)
    engine_output = EngineOutput(results=[], candidates=[evidence])

    output = classifier.classify_all_sync(engine_output, [src], [tgt])

    expected_id = generate_relationship_id(["GTW-E03"], ["BANK-E03"])
    assert output.classified_results[0].relationship_id == expected_id


# ---------------------------------------------------------------------------
# 11. Async classifier
# ---------------------------------------------------------------------------


def test_async_classifier():
    """classify_all works correctly via asyncio.run."""
    src = _make_record("GTW-D05", currency="INR")
    tgt = _make_record("BANK-D05", currency="USD", source="BANK")

    result = _make_committed_result(["GTW-D05"], ["BANK-D05"])

    def handler(case):
        return ExceptionClassificationDecision(
            exception_type="CURRENCY_MISMATCH",
            severity="HIGH",
            flag_for_review=True,
            reasoning="test",
            confidence=0.9,
        )

    provider = MockProvider(exception_handler=handler)
    classifier = AIExceptionClassifier(provider=provider)
    engine_output = EngineOutput(results=[result], candidates=[])

    output = asyncio.run(classifier.classify_all(engine_output, [src], [tgt]))

    assert len(output.classified_results) == 1
    assert output.classified_results[0].exception_type == ExceptionType.CURRENCY_MISMATCH


# ---------------------------------------------------------------------------
# 12. Sync wrapper
# ---------------------------------------------------------------------------


def test_sync_wrapper():
    """classify_all_sync produces same results as async path."""
    src = _make_record("GTW-D05", currency="INR")
    tgt = _make_record("BANK-D05", currency="USD", source="BANK")

    result = _make_committed_result(["GTW-D05"], ["BANK-D05"])

    def handler(case):
        return ExceptionClassificationDecision(
            exception_type="CURRENCY_MISMATCH",
            severity="HIGH",
            flag_for_review=True,
            reasoning="test",
            confidence=0.9,
        )

    provider = MockProvider(exception_handler=handler)
    classifier = AIExceptionClassifier(provider=provider)
    engine_output = EngineOutput(results=[result], candidates=[])

    output = classifier.classify_all_sync(engine_output, [src], [tgt])

    assert len(output.classified_results) == 1
    assert output.classified_results[0].exception_type == ExceptionType.CURRENCY_MISMATCH


# ---------------------------------------------------------------------------
# 13. Provider timeout / retry
# ---------------------------------------------------------------------------


def test_provider_timeout_retry():
    """Timeout on first attempt → retry → success."""
    call_count = 0

    def handler(case):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise TimeoutError("Simulated timeout")
        return ExceptionClassificationDecision(
            exception_type="UNKNOWN",
            severity="HIGH",
            flag_for_review=True,
            reasoning="Recovered after retry",
            confidence=0.7,
        )

    src = _make_record("GTW-D09")
    tgt = _make_record("BANK-D09", source="BANK")
    result = _make_committed_result(["GTW-D09"], ["BANK-D09"])

    provider = MockProvider(exception_handler=handler)
    classifier = AIExceptionClassifier(provider=provider, max_retries=2)
    engine_output = EngineOutput(results=[result], candidates=[])

    output = classifier.classify_all_sync(engine_output, [src], [tgt])

    assert len(output.classified_results) == 1
    assert call_count == 2  # First failed, second succeeded


# ---------------------------------------------------------------------------
# 14. Provider unavailable
# ---------------------------------------------------------------------------


def test_provider_unavailable():
    """All retries fail → FailedClassification."""
    def handler(case):
        raise ConnectionError("Provider unavailable")

    src = _make_record("GTW-D09")
    tgt = _make_record("BANK-D09", source="BANK")
    result = _make_committed_result(["GTW-D09"], ["BANK-D09"])

    provider = MockProvider(exception_handler=handler)
    classifier = AIExceptionClassifier(provider=provider, max_retries=1)
    engine_output = EngineOutput(results=[result], candidates=[])

    output = classifier.classify_all_sync(engine_output, [src], [tgt])

    assert len(output.classified_results) == 0
    assert len(output.failed_cases) == 1
    assert output.failed_cases[0].attempts == 2  # initial + 1 retry


# ---------------------------------------------------------------------------
# 15. Malformed structured output retry
# ---------------------------------------------------------------------------


def test_malformed_json_retry():
    """Malformed response → retry → valid response."""
    call_count = 0

    def handler(case):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ValueError("Malformed JSON from provider")
        return ExceptionClassificationDecision(
            exception_type="UNKNOWN",
            severity="HIGH",
            flag_for_review=True,
            reasoning="Recovered",
            confidence=0.6,
        )

    src = _make_record("GTW-D09")
    tgt = _make_record("BANK-D09", source="BANK")
    result = _make_committed_result(["GTW-D09"], ["BANK-D09"])

    provider = MockProvider(exception_handler=handler)
    classifier = AIExceptionClassifier(provider=provider, max_retries=2)
    engine_output = EngineOutput(results=[result], candidates=[])

    output = classifier.classify_all_sync(engine_output, [src], [tgt])

    assert len(output.classified_results) == 1
    assert call_count == 2


# ---------------------------------------------------------------------------
# 16. Retry exhaustion
# ---------------------------------------------------------------------------


def test_retry_exhaustion():
    """All retries produce errors → FailedClassification."""
    def handler(case):
        raise RuntimeError("Persistent failure")

    src = _make_record("GTW-D05")
    tgt = _make_record("BANK-D05", source="BANK")
    result = _make_committed_result(["GTW-D05"], ["BANK-D05"])

    provider = MockProvider(exception_handler=handler)
    classifier = AIExceptionClassifier(provider=provider, max_retries=2)
    engine_output = EngineOutput(results=[result], candidates=[])

    output = classifier.classify_all_sync(engine_output, [src], [tgt])

    assert len(output.classified_results) == 0
    assert len(output.failed_cases) == 1
    assert output.failed_cases[0].attempts == 3  # initial + 2 retries


# ---------------------------------------------------------------------------
# 17. D-08 POSSIBLE_DUPLICATE
# ---------------------------------------------------------------------------


def test_d08_possible_duplicate():
    """D-08: AI selects 0 targets, emits POSSIBLE_DUPLICATE with target_record_ids=[]."""
    src = _make_record("GTW-D08", txn_date="2025-01-16", stl_date="2025-01-16")
    tgt1 = _make_record("BANK-E03", source="BANK")
    tgt2 = _make_record("BANK-D03", source="BANK", stl_date="2025-01-18")

    evidence = CandidateRelationshipEvidence(
        source_record_ids=["GTW-D08"],
        candidate_target_record_ids=["BANK-E03", "BANK-D03"],
        relationship_context="Ambiguous pool",
    )

    def handler(case):
        return CandidateSelectionDecision(
            selected_target_record_ids=[],  # No valid counterpart
            relationship_type="1:1",
            outcome="EXCEPTION",
            exception_type="POSSIBLE_DUPLICATE",
            severity="MEDIUM",
            flag_for_review=True,
            reconciled_amount="5000.00",
            reasoning="Near-duplicate of another gateway record",
            confidence=0.7,
        )

    provider = MockProvider(candidate_handler=handler)
    classifier = AIExceptionClassifier(provider=provider)
    engine_output = EngineOutput(results=[], candidates=[evidence])

    output = classifier.classify_all_sync(engine_output, [src], [tgt1, tgt2])

    assert len(output.classified_results) == 1
    d08 = output.classified_results[0]
    assert d08.source_record_ids == ["GTW-D08"]
    assert d08.target_record_ids == []
    assert d08.exception_type == ExceptionType.POSSIBLE_DUPLICATE
    assert d08.relationship_type == RelationshipType.ONE_TO_ONE
    assert d08.outcome == ReconciliationOutcome.EXCEPTION


# ---------------------------------------------------------------------------
# 18. E-03 candidate selection
# ---------------------------------------------------------------------------


def test_e03_candidate_selection():
    """E-03: AI selects BANK-E03 from pool, emits 1:1 MATCHED."""
    src = _make_record("GTW-E03")
    tgt1 = _make_record("BANK-E03", source="BANK")
    tgt2 = _make_record("BANK-D03", source="BANK", stl_date="2025-01-18")

    evidence = CandidateRelationshipEvidence(
        source_record_ids=["GTW-E03"],
        candidate_target_record_ids=["BANK-E03", "BANK-D03"],
        relationship_context="Ambiguous pool",
    )

    def handler(case):
        return CandidateSelectionDecision(
            selected_target_record_ids=["BANK-E03"],
            relationship_type="1:1",
            outcome="MATCHED",
            exception_type=None,
            severity=None,
            flag_for_review=False,
            reconciled_amount="5000.00",
            reasoning="BANK-E03 has closer settlement date",
            confidence=0.85,
        )

    provider = MockProvider(candidate_handler=handler)
    classifier = AIExceptionClassifier(provider=provider)
    engine_output = EngineOutput(results=[], candidates=[evidence])

    output = classifier.classify_all_sync(engine_output, [src], [tgt1, tgt2])

    assert len(output.classified_results) == 1
    e03 = output.classified_results[0]
    assert e03.source_record_ids == ["GTW-E03"]
    assert e03.target_record_ids == ["BANK-E03"]
    assert e03.relationship_type == RelationshipType.ONE_TO_ONE
    assert e03.outcome == ReconciliationOutcome.MATCHED


# ---------------------------------------------------------------------------
# 19. E-06 SPLIT_SETTLEMENT
# ---------------------------------------------------------------------------


def test_e06_split_settlement():
    """E-06: AI classifies committed 1:N as SPLIT_SETTLEMENT."""
    src = _make_record("GTW-E06", amount="10000.00", txn_date="2025-03-10", stl_date="2025-03-10")
    tgt1 = _make_record("BANK-E06-1", amount="6000.00", txn_date="2025-03-12", stl_date="2025-03-12", source="BANK")
    tgt2 = _make_record("BANK-E06-2", amount="2500.00", txn_date="2025-03-13", stl_date="2025-03-13", source="BANK")

    result = _make_committed_result(
        ["GTW-E06"], ["BANK-E06-1", "BANK-E06-2"],
        rel_type="1:N", amount="10000.00",
    )

    def handler(case):
        return ExceptionClassificationDecision(
            exception_type="SPLIT_SETTLEMENT",
            severity="HIGH",
            flag_for_review=True,
            reasoning="Aggregate shortfall in split settlement",
            confidence=0.9,
        )

    provider = MockProvider(exception_handler=handler)
    classifier = AIExceptionClassifier(provider=provider)
    engine_output = EngineOutput(results=[result], candidates=[])

    output = classifier.classify_all_sync(engine_output, [src], [tgt1, tgt2])

    assert len(output.classified_results) == 1
    e06 = output.classified_results[0]
    assert e06.exception_type == ExceptionType.SPLIT_SETTLEMENT
    assert e06.relationship_type == RelationshipType.ONE_TO_MANY


# ---------------------------------------------------------------------------
# 20. D-05 CURRENCY_MISMATCH
# ---------------------------------------------------------------------------


def test_d05_currency_mismatch():
    """D-05: AI classifies committed 1:1 as CURRENCY_MISMATCH."""
    src = _make_record("GTW-D05", currency="INR")
    tgt = _make_record("BANK-D05", currency="USD", source="BANK")

    result = _make_committed_result(["GTW-D05"], ["BANK-D05"])

    def handler(case):
        return ExceptionClassificationDecision(
            exception_type="CURRENCY_MISMATCH",
            severity="HIGH",
            flag_for_review=True,
            reasoning="Currency mismatch: INR vs USD",
            confidence=0.95,
        )

    provider = MockProvider(exception_handler=handler)
    classifier = AIExceptionClassifier(provider=provider)
    engine_output = EngineOutput(results=[result], candidates=[])

    output = classifier.classify_all_sync(engine_output, [src], [tgt])

    assert len(output.classified_results) == 1
    assert output.classified_results[0].exception_type == ExceptionType.CURRENCY_MISMATCH


# ---------------------------------------------------------------------------
# 21. D-06 PARTIAL_SETTLEMENT
# ---------------------------------------------------------------------------


def test_d06_partial_settlement():
    """D-06: AI classifies committed 1:1 as PARTIAL_SETTLEMENT."""
    src = _make_record("GTW-D06", amount="8000.00")
    tgt = _make_record("BANK-D06", amount="6000.00", source="BANK")

    result = _make_committed_result(["GTW-D06"], ["BANK-D06"], amount="8000.00")

    def handler(case):
        return ExceptionClassificationDecision(
            exception_type="PARTIAL_SETTLEMENT",
            severity="HIGH",
            flag_for_review=True,
            reasoning="Significant shortfall",
            confidence=0.85,
        )

    provider = MockProvider(exception_handler=handler)
    classifier = AIExceptionClassifier(provider=provider)
    engine_output = EngineOutput(results=[result], candidates=[])

    output = classifier.classify_all_sync(engine_output, [src], [tgt])

    assert len(output.classified_results) == 1
    assert output.classified_results[0].exception_type == ExceptionType.PARTIAL_SETTLEMENT


# ---------------------------------------------------------------------------
# 22. D-09 UNKNOWN
# ---------------------------------------------------------------------------


def test_d09_unknown():
    """D-09: AI classifies as UNKNOWN."""
    src = _make_record("GTW-D09")
    tgt = _make_record("BANK-D09", source="BANK")

    result = _make_committed_result(["GTW-D09"], ["BANK-D09"])

    def handler(case):
        return ExceptionClassificationDecision(
            exception_type="UNKNOWN",
            severity="HIGH",
            flag_for_review=True,
            reasoning="No known pattern applies",
            confidence=0.4,
        )

    provider = MockProvider(exception_handler=handler)
    classifier = AIExceptionClassifier(provider=provider)
    engine_output = EngineOutput(results=[result], candidates=[])

    output = classifier.classify_all_sync(engine_output, [src], [tgt])

    assert len(output.classified_results) == 1
    assert output.classified_results[0].exception_type == ExceptionType.UNKNOWN


# ---------------------------------------------------------------------------
# 23. Candidate evidence is non-consuming (E-03 + D-08 overlap)
# ---------------------------------------------------------------------------


def test_candidate_evidence_non_consuming():
    """Resolving E-03 must NOT consume records from D-08's candidate evidence.

    E-03 and D-08 share overlapping candidate target IDs (BANK-E03, BANK-D03).
    Each case must receive its full candidate pool regardless of classification order.
    """
    src_e03 = _make_record("GTW-E03")
    src_d08 = _make_record("GTW-D08", txn_date="2025-01-16", stl_date="2025-01-16")
    tgt1 = _make_record("BANK-E03", source="BANK")
    tgt2 = _make_record("BANK-D03", source="BANK", stl_date="2025-01-18")

    evidence_e03 = CandidateRelationshipEvidence(
        source_record_ids=["GTW-E03"],
        candidate_target_record_ids=["BANK-E03", "BANK-D03"],
        relationship_context="Ambiguous pool",
    )
    evidence_d08 = CandidateRelationshipEvidence(
        source_record_ids=["GTW-D08"],
        candidate_target_record_ids=["BANK-E03", "BANK-D03"],
        relationship_context="Ambiguous pool",
    )

    cases_received = []

    def handler(case):
        cases_received.append(case)
        if case.source_record_ids == ["GTW-E03"]:
            return CandidateSelectionDecision(
                selected_target_record_ids=["BANK-E03"],
                relationship_type="1:1",
                outcome="MATCHED",
                exception_type=None,
                severity=None,
                flag_for_review=False,
                reconciled_amount="5000.00",
                reasoning="E-03 selects BANK-E03",
                confidence=0.8,
            )
        else:
            return CandidateSelectionDecision(
                selected_target_record_ids=[],
                relationship_type="1:1",
                outcome="EXCEPTION",
                exception_type="POSSIBLE_DUPLICATE",
                severity="MEDIUM",
                flag_for_review=True,
                reconciled_amount="5000.00",
                reasoning="D-08 is a near-duplicate",
                confidence=0.7,
            )

    provider = MockProvider(candidate_handler=handler)
    classifier = AIExceptionClassifier(provider=provider)
    engine_output = EngineOutput(
        results=[],
        candidates=[evidence_e03, evidence_d08],
    )

    output = classifier.classify_all_sync(
        engine_output,
        [src_e03, src_d08],
        [tgt1, tgt2],
    )

    assert len(output.classified_results) == 2
    assert len(output.failed_cases) == 0

    # Verify both cases received their FULL candidate pools
    assert len(cases_received) == 2

    for case in cases_received:
        # Both cases should have both candidates available
        assert set(case.candidate_target_record_ids) == {"BANK-E03", "BANK-D03"}

    # Verify results
    e03_result = next(r for r in output.classified_results if r.source_record_ids == ["GTW-E03"])
    d08_result = next(r for r in output.classified_results if r.source_record_ids == ["GTW-D08"])

    assert e03_result.target_record_ids == ["BANK-E03"]
    assert e03_result.outcome == ReconciliationOutcome.MATCHED

    assert d08_result.target_record_ids == []
    assert d08_result.exception_type == ExceptionType.POSSIBLE_DUPLICATE
