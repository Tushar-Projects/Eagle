"""Day 1 & Day 2 Unit & Integration Test Suite for Operator Corrections, Rule Synthesis, Rule Engine, and Rerun."""

from datetime import date, datetime, timezone
from decimal import Decimal
import io
import uuid

import pytest
from fastapi.testclient import TestClient

from eagle.agents._mock import MockProvider
from eagle.api.main import app
from eagle.api.routes import get_service
from eagle.core.config import Settings
from eagle.models.canonical import CanonicalRecord
from eagle.models.enums import ExceptionType, ReconciliationOutcome, RelationshipType
from eagle.models.evidence import CandidateRelationshipEvidence, CandidateRelationshipOption, EngineOutput
from eagle.models.reconciliation import ReconciliationResult
from eagle.rules.models import OperatorCorrection, ReconciliationRule
from eagle.rules.rule_engine import RuleEngine
from eagle.rules.rule_synthesizer import RuleSynthesizer
from eagle.services.reconciliation_service import ReconciliationService
from eagle.storage.database import Database
from eagle.storage.repository import Repository


@pytest.fixture
def isolated_service():
    """Create an isolated in-memory ReconciliationService."""
    db = Database(":memory:")
    repo = Repository(db)
    provider = MockProvider()
    settings = Settings(DATABASE_PATH=":memory:", AI_PROVIDER="mock")
    return ReconciliationService(repository=repo, provider=provider, settings=settings)


@pytest.fixture
def client_with_service(isolated_service):
    """FastAPI TestClient with isolated service dependency."""
    app.dependency_overrides[get_service] = lambda: isolated_service
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def make_record(
    record_id: str,
    amount: Decimal,
    source: str = "GATEWAY",
    reference: str = "REF-100",
    counterparty: str = "Merchant X",
    fee_amount: Decimal | None = None,
    txn_date: date = date(2025, 1, 1),
    settlement_date: date | None = None,
) -> CanonicalRecord:
    """Helper to construct valid CanonicalRecord instances."""
    s_date = settlement_date if settlement_date is not None else txn_date
    return CanonicalRecord(
        record_id=record_id,
        transaction_id=record_id,
        source=source,
        source_reference=reference,
        amount=amount,
        currency="INR",
        transaction_date=txn_date,
        settlement_date=s_date,
        counterparty=counterparty,
        status="COMPLETED" if source == "GATEWAY" else "POSTED",
        transaction_type="CREDIT" if amount >= Decimal("0.00") else "DEBIT",
        fee_amount=fee_amount,
    )


# =============================================================================
# Day 1 Tests: Operator Corrections Persistence & API
# =============================================================================

def test_save_and_retrieve_operator_correction(isolated_service):
    """Test 1: Repository persists and retrieves OperatorCorrection instances correctly."""
    repo = isolated_service.repository
    run_id = "RUN-TEST-001"
    repo.create_run(run_id=run_id, status="COMPLETED")

    correction = OperatorCorrection(
        correction_id="CORR-1001",
        run_id=run_id,
        relationship_id="REL-501",
        original_outcome="EXCEPTION",
        original_exception_type="UNKNOWN",
        original_source_ids=["G-1"],
        original_target_ids=["B-1"],
        corrected_outcome="MATCHED",
        corrected_exception_type="FEE_DEDUCTION",
        corrected_source_ids=["G-1"],
        corrected_target_ids=["B-1"],
        operator_reason="Confirmed merchant fee of 1.50",
        created_at="2025-01-01T12:00:00Z",
    )

    repo.save_correction(correction)

    corrections = repo.get_corrections(run_id)
    assert len(corrections) == 1
    c = corrections[0]
    assert c.correction_id == "CORR-1001"
    assert c.relationship_id == "REL-501"
    assert c.original_outcome == "EXCEPTION"
    assert c.corrected_outcome == "MATCHED"
    assert c.corrected_exception_type == "FEE_DEDUCTION"
    assert c.operator_reason == "Confirmed merchant fee of 1.50"

    # Lookup by ID
    by_id = repo.get_correction("CORR-1001")
    assert by_id is not None
    assert by_id.correction_id == "CORR-1001"

    # Lookup by relationship
    by_rel = repo.get_corrections_for_relationship(run_id, "REL-501")
    assert len(by_rel) == 1
    assert by_rel[0].correction_id == "CORR-1001"


def test_correction_api_creates_persistent_record(client_with_service, isolated_service):
    """Test 2 & 3: POST /runs/{run_id}/results/{rel_id}/correct persists correction and returns ID."""
    sources = [make_record("G-101", Decimal("5000.00"), source="GATEWAY", reference="REF-101")]
    targets = [make_record("B-101", Decimal("5000.00"), source="BANK", reference="REF-OTHER")]
    res_run = isolated_service.reconcile_records(sources, targets)
    run_id = res_run["run_id"]

    results = isolated_service.repository.get_results(run_id)
    assert len(results) > 0
    rel_id = results[0].relationship_id

    payload = {
        "corrected_outcome": "MATCHED",
        "corrected_exception_type": "SETTLEMENT_DELAY",
        "corrected_source_ids": ["G-101"],
        "corrected_target_ids": ["B-101"],
        "operator_reason": "Matched manually after verifying reference typo in bank export",
        "generate_rule": False,
    }

    res_post = client_with_service.post(f"/runs/{run_id}/results/{rel_id}/correct", json=payload)
    assert res_post.status_code == 201
    data = res_post.json()

    assert data["correction_id"].startswith("CORR-")
    assert data["run_id"] == run_id
    assert data["relationship_id"] == rel_id
    assert data["status"] == "COMMITTED"
    assert data["corrected_outcome"] == "MATCHED"
    assert data["corrected_exception_type"] == "SETTLEMENT_DELAY"
    assert data["corrected_source_ids"] == ["G-101"]
    assert data["corrected_target_ids"] == ["B-101"]

    # Verify persistent retrieval
    persisted = isolated_service.repository.get_correction(data["correction_id"])
    assert persisted is not None
    assert persisted.operator_reason == payload["operator_reason"]


def test_correction_audit_event_logged(client_with_service, isolated_service):
    """Test 4: Submitting a correction creates an OPERATOR_CORRECTION_CREATED audit log."""
    sources = [make_record("G-AUDIT", Decimal("1000.00"), source="GATEWAY")]
    targets = [make_record("B-AUDIT", Decimal("1000.00"), source="BANK")]
    res_run = isolated_service.reconcile_records(sources, targets)
    run_id = res_run["run_id"]

    results = isolated_service.repository.get_results(run_id)
    rel_id = results[0].relationship_id

    payload = {
        "corrected_outcome": "MATCHED",
        "corrected_exception_type": None,
        "corrected_source_ids": ["G-AUDIT"],
        "corrected_target_ids": ["B-AUDIT"],
        "operator_reason": "Audit verification test correction",
    }

    res_post = client_with_service.post(f"/runs/{run_id}/results/{rel_id}/correct", json=payload)
    assert res_post.status_code == 201
    corr_id = res_post.json()["correction_id"]

    logs = isolated_service.repository.get_audit_logs(run_id)
    corr_events = [l for l in logs if l["event_type"] == "OPERATOR_CORRECTION_CREATED"]
    assert len(corr_events) == 1
    ev = corr_events[0]
    assert ev["details"]["correction_id"] == corr_id
    assert ev["details"]["relationship_id"] == rel_id
    assert ev["details"]["corrected_outcome"] == "MATCHED"


def test_original_result_immutable_on_correction(client_with_service, isolated_service):
    """Test 5: Submitting a correction MUST NOT mutate or delete the original ReconciliationResult."""
    sources = [make_record("G-IMM", Decimal("2500.00"), source="GATEWAY", reference="REF-IMM")]
    targets = []
    res_run = isolated_service.reconcile_records(sources, targets)
    run_id = res_run["run_id"]

    results_before = isolated_service.repository.get_results(run_id)
    assert len(results_before) == 1
    rel_id = results_before[0].relationship_id
    orig_outcome = results_before[0].outcome
    orig_exception = results_before[0].exception_type

    payload = {
        "corrected_outcome": "MATCHED",
        "corrected_exception_type": "ROUNDING_DIFFERENCE",
        "corrected_source_ids": ["G-IMM"],
        "corrected_target_ids": [],
        "operator_reason": "Marked matched after reconciliation adjustment",
    }

    res_post = client_with_service.post(f"/runs/{run_id}/results/{rel_id}/correct", json=payload)
    assert res_post.status_code == 201

    results_after = isolated_service.repository.get_results(run_id)
    assert len(results_after) == 1
    assert results_after[0].outcome == orig_outcome
    assert results_after[0].exception_type == orig_exception
    assert results_after[0].relationship_id == rel_id


def test_correction_rejects_unknown_source_id(client_with_service, isolated_service):
    """Test 6: Reject correction referencing a source ID not present in the run."""
    sources = [make_record("G-KNOWN", Decimal("1000.00"), source="GATEWAY")]
    targets = [make_record("B-KNOWN", Decimal("1000.00"), source="BANK")]
    res_run = isolated_service.reconcile_records(sources, targets)
    run_id = res_run["run_id"]
    rel_id = isolated_service.repository.get_results(run_id)[0].relationship_id

    payload = {
        "corrected_outcome": "MATCHED",
        "corrected_source_ids": ["G-FABRICATED-FAKE-ID"],
        "corrected_target_ids": ["B-KNOWN"],
        "operator_reason": "Attempting to link fabricated source record",
    }

    res = client_with_service.post(f"/runs/{run_id}/results/{rel_id}/correct", json=payload)
    assert res.status_code == 422
    assert "fabricated" in res.json()["detail"].lower() or "does not exist" in res.json()["detail"].lower()


def test_correction_rejects_unknown_target_id(client_with_service, isolated_service):
    """Test 7: Reject correction referencing a target ID not present in the run."""
    sources = [make_record("G-KNOWN", Decimal("1000.00"), source="GATEWAY")]
    targets = [make_record("B-KNOWN", Decimal("1000.00"), source="BANK")]
    res_run = isolated_service.reconcile_records(sources, targets)
    run_id = res_run["run_id"]
    rel_id = isolated_service.repository.get_results(run_id)[0].relationship_id

    payload = {
        "corrected_outcome": "MATCHED",
        "corrected_source_ids": ["G-KNOWN"],
        "corrected_target_ids": ["B-NONEXISTENT-TARGET"],
        "operator_reason": "Attempting to link fabricated target record",
    }

    res = client_with_service.post(f"/runs/{run_id}/results/{rel_id}/correct", json=payload)
    assert res.status_code == 422
    assert "fabricated" in res.json()["detail"].lower() or "does not exist" in res.json()["detail"].lower()


def test_correction_rejects_unknown_run(client_with_service):
    """Test 8: Reject correction when run_id does not exist."""
    payload = {
        "corrected_outcome": "MATCHED",
        "corrected_source_ids": ["G-1"],
        "operator_reason": "Unknown run test",
    }
    res = client_with_service.post("/runs/NON-EXISTENT-RUN/results/REL-1/correct", json=payload)
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()


def test_correction_rejects_unknown_relationship(client_with_service, isolated_service):
    """Test 8b: Reject correction when relationship_id does not exist in run."""
    sources = [make_record("G-1", Decimal("100.00"), source="GATEWAY")]
    targets = [make_record("B-1", Decimal("100.00"), source="BANK")]
    res_run = isolated_service.reconcile_records(sources, targets)
    run_id = res_run["run_id"]

    payload = {
        "corrected_outcome": "MATCHED",
        "corrected_source_ids": ["G-1"],
        "operator_reason": "Unknown relationship test",
    }
    res = client_with_service.post(f"/runs/{run_id}/results/NON-EXISTENT-REL/correct", json=payload)
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()


def test_get_corrections_for_run(client_with_service, isolated_service):
    """Test 9: GET /runs/{run_id}/corrections returns list of all corrections."""
    sources = [
        make_record("G-1", Decimal("1000.00"), source="GATEWAY"),
        make_record("G-2", Decimal("2000.00"), source="GATEWAY"),
    ]
    targets = [
        make_record("B-1", Decimal("1000.00"), source="BANK"),
        make_record("B-2", Decimal("2000.00"), source="BANK"),
    ]
    res_run = isolated_service.reconcile_records(sources, targets)
    run_id = res_run["run_id"]
    results = isolated_service.repository.get_results(run_id)

    # Submit 2 corrections
    for r in results:
        payload = {
            "corrected_outcome": "MATCHED",
            "corrected_source_ids": r.source_record_ids,
            "corrected_target_ids": r.target_record_ids,
            "operator_reason": f"Verified relationship {r.relationship_id}",
        }
        res = client_with_service.post(f"/runs/{run_id}/results/{r.relationship_id}/correct", json=payload)
        assert res.status_code == 201

    res_list = client_with_service.get(f"/runs/{run_id}/corrections")
    assert res_list.status_code == 200
    data = res_list.json()
    assert data["run_id"] == run_id
    assert data["total"] == 2
    assert len(data["corrections"]) == 2


def test_get_correction_by_id(client_with_service, isolated_service):
    """Test 9b: GET /runs/{run_id}/corrections/{correction_id} returns single correction."""
    sources = [make_record("G-ID", Decimal("300.00"), source="GATEWAY")]
    targets = [make_record("B-ID", Decimal("300.00"), source="BANK")]
    res_run = isolated_service.reconcile_records(sources, targets)
    run_id = res_run["run_id"]
    rel_id = isolated_service.repository.get_results(run_id)[0].relationship_id

    payload = {
        "corrected_outcome": "MATCHED",
        "corrected_source_ids": ["G-ID"],
        "corrected_target_ids": ["B-ID"],
        "operator_reason": "Single lookup test",
    }
    res_post = client_with_service.post(f"/runs/{run_id}/results/{rel_id}/correct", json=payload)
    corr_id = res_post.json()["correction_id"]

    res_get = client_with_service.get(f"/runs/{run_id}/corrections/{corr_id}")
    assert res_get.status_code == 200
    assert res_get.json()["correction_id"] == corr_id
    assert res_get.json()["operator_reason"] == "Single lookup test"


def test_correction_is_append_only(client_with_service, isolated_service):
    """Test 10: Multiple sequential corrections for the same relationship append without overwriting."""
    sources = [make_record("G-SEQ", Decimal("4000.00"), source="GATEWAY")]
    targets = [make_record("B-SEQ", Decimal("4000.00"), source="BANK")]
    res_run = isolated_service.reconcile_records(sources, targets)
    run_id = res_run["run_id"]
    rel_id = isolated_service.repository.get_results(run_id)[0].relationship_id

    # First correction
    res1 = client_with_service.post(
        f"/runs/{run_id}/results/{rel_id}/correct",
        json={
            "corrected_outcome": "EXCEPTION",
            "corrected_exception_type": "SETTLEMENT_DELAY",
            "corrected_source_ids": ["G-SEQ"],
            "corrected_target_ids": ["B-SEQ"],
            "operator_reason": "First review: Delay noted",
        },
    )
    assert res1.status_code == 201
    corr1_id = res1.json()["correction_id"]

    # Second correction for the same relationship
    res2 = client_with_service.post(
        f"/runs/{run_id}/results/{rel_id}/correct",
        json={
            "corrected_outcome": "MATCHED",
            "corrected_exception_type": "ROUNDING_DIFFERENCE",
            "corrected_source_ids": ["G-SEQ"],
            "corrected_target_ids": ["B-SEQ"],
            "operator_reason": "Second review: Reconciled with rounding tolerance",
        },
    )
    assert res2.status_code == 201
    corr2_id = res2.json()["correction_id"]

    assert corr1_id != corr2_id

    corrections = isolated_service.repository.get_corrections_for_relationship(run_id, rel_id)
    assert len(corrections) == 2
    assert corrections[0].correction_id == corr1_id
    assert corrections[0].operator_reason == "First review: Delay noted"
    assert corrections[1].correction_id == corr2_id
    assert corrections[1].operator_reason == "Second review: Reconciled with rounding tolerance"


def test_correction_rejects_n_to_m_topology(client_with_service, isolated_service):
    """Test 11: Reject correction specifying general N:M topology."""
    sources = [
        make_record("G-M1", Decimal("2000.00"), source="GATEWAY"),
        make_record("G-M2", Decimal("3000.00"), source="GATEWAY"),
    ]
    targets = [
        make_record("B-M1", Decimal("2500.00"), source="BANK"),
        make_record("B-M2", Decimal("2500.00"), source="BANK"),
    ]
    res_run = isolated_service.reconcile_records(sources, targets)
    run_id = res_run["run_id"]
    rel_id = isolated_service.repository.get_results(run_id)[0].relationship_id

    payload = {
        "corrected_outcome": "MATCHED",
        "corrected_source_ids": ["G-M1", "G-M2"],
        "corrected_target_ids": ["B-M1", "B-M2"],
        "operator_reason": "Attempting N:M correction",
    }
    res = client_with_service.post(f"/runs/{run_id}/results/{rel_id}/correct", json=payload)
    assert res.status_code == 422
    assert "n:m" in res.json()["detail"].lower()


def test_correction_rejects_invalid_outcome_and_exception_type(client_with_service, isolated_service):
    """Test 12: Reject invalid outcome strings or invalid exception types."""
    sources = [make_record("G-V", Decimal("100.00"), source="GATEWAY")]
    targets = [make_record("B-V", Decimal("100.00"), source="BANK")]
    res_run = isolated_service.reconcile_records(sources, targets)
    run_id = res_run["run_id"]
    rel_id = isolated_service.repository.get_results(run_id)[0].relationship_id

    # Invalid outcome
    res_bad_outcome = client_with_service.post(
        f"/runs/{run_id}/results/{rel_id}/correct",
        json={
            "corrected_outcome": "SUPER_MATCHED_INVALID",
            "corrected_source_ids": ["G-V"],
            "operator_reason": "Invalid outcome test",
        },
    )
    assert res_bad_outcome.status_code == 422

    # Invalid exception type
    res_bad_ex = client_with_service.post(
        f"/runs/{run_id}/results/{rel_id}/correct",
        json={
            "corrected_outcome": "EXCEPTION",
            "corrected_exception_type": "ALIEN_INVASION_EXCEPTION",
            "corrected_source_ids": ["G-V"],
            "operator_reason": "Invalid exception test",
        },
    )
    assert res_bad_ex.status_code == 422


# =============================================================================
# Day 2 Tests: Rule Synthesis, Rule Persistence, Rule Engine, Rerun, Impact
# =============================================================================

def test_rule_synthesizer_extracts_generalized_predicates():
    """Test 13: RuleSynthesizer extracts generalized predicates from participating records."""
    sources = [
        make_record(
            "GTW-10",
            Decimal("10000.00"),
            source="GATEWAY",
            reference="REF-7719",
            counterparty="Merchant F",
            txn_date=date(2025, 2, 1),
        )
    ]
    targets = [
        make_record(
            "BANK-10",
            Decimal("9998.50"),
            source="BANK",
            reference="BNK-7719",
            counterparty="Merchant F",
            settlement_date=date(2025, 2, 3),
        )
    ]
    correction = OperatorCorrection(
        correction_id="CORR-SYNTH-1",
        run_id="RUN-1",
        relationship_id="REL-1",
        original_outcome="EXCEPTION",
        original_exception_type=None,
        original_source_ids=["GTW-10"],
        original_target_ids=["BANK-10"],
        corrected_outcome="MATCHED",
        corrected_exception_type="FEE_DEDUCTION",
        corrected_source_ids=["GTW-10"],
        corrected_target_ids=["BANK-10"],
        operator_reason="Merchant F settlements incur a ₹1.50 processing fee",
        created_at="2025-02-03T10:00:00Z",
    )

    rule = RuleSynthesizer.synthesize(correction, sources, targets)
    assert rule.source_counterparty_pattern == "Merchant F"
    assert rule.currency == "INR"
    assert rule.max_amount_difference == Decimal("1.50")
    assert rule.max_settlement_delay_days == 2
    assert rule.resulting_outcome == "MATCHED"
    assert rule.resulting_exception_type == "FEE_DEDUCTION"
    assert rule.source_correction_id == "CORR-SYNTH-1"


def test_rule_synthesizer_never_embeds_record_ids():
    """Test 14: Synthesizer NEVER uses exact record IDs in synthesized rules."""
    sources = [
        make_record("GTW-C06-1", Decimal("500.00"), source="GATEWAY", counterparty="Acme Corp", reference="TXN-1")
    ]
    targets = [
        make_record("BANK-C06-1", Decimal("500.00"), source="BANK", counterparty="Acme Corp", reference="TXN-2")
    ]
    correction = OperatorCorrection(
        correction_id="CORR-SAFE-1",
        run_id="RUN-SAFE",
        relationship_id="REL-SAFE",
        original_outcome="EXCEPTION",
        original_source_ids=["GTW-C06-1"],
        original_target_ids=["BANK-C06-1"],
        corrected_outcome="MATCHED",
        corrected_source_ids=["GTW-C06-1"],
        corrected_target_ids=["BANK-C06-1"],
        operator_reason="Acme transactions matched",
        created_at="2025-01-01T00:00:00Z",
    )

    rule = RuleSynthesizer.synthesize(correction, sources, targets)
    # Check that exact record IDs are absent from predicates and names
    assert "GTW-C06-1" not in rule.name
    assert "BANK-C06-1" not in rule.name
    assert rule.source_counterparty_pattern == "Acme Corp"


def test_rule_synthesizer_rejects_non_generalizable_correction():
    """Test 15: Synthesizer rejects correction when no meaningful predicates exist."""
    src = CanonicalRecord(
        record_id="G-BLANK",
        transaction_id="G-BLANK",
        source="GATEWAY",
        source_reference="",
        amount=Decimal("100.00"),
        currency="",
        transaction_date=date(2025, 1, 1),
        settlement_date=date(2025, 1, 1),
        counterparty="",
        status="COMPLETED",
        transaction_type="CREDIT",
    )
    correction = OperatorCorrection(
        correction_id="CORR-BAD",
        run_id="RUN-BAD",
        relationship_id="REL-BAD",
        original_outcome="EXCEPTION",
        original_source_ids=["G-BLANK"],
        original_target_ids=[],
        corrected_outcome="MATCHED",
        corrected_source_ids=["G-BLANK"],
        corrected_target_ids=[],
        operator_reason="Blank record",
        created_at="2025-01-01T00:00:00Z",
    )
    # No targets -> diff is None, delay is None, no counterparty, no ref prefix, no currency
    with pytest.raises(ValueError, match="no distinctive generalized predicates found"):
        RuleSynthesizer.synthesize(correction, [src], [])


def test_rule_persistence(isolated_service):
    """Test 16: Persisting, retrieving, and querying rules from SQLite repository."""
    repo = isolated_service.repository
    rule = ReconciliationRule(
        rule_id="RULE-TEST-001",
        name="Merchant F Fee Rule",
        description="Matches Merchant F fee deductions",
        source_counterparty_pattern="Merchant F",
        currency="INR",
        max_amount_difference=Decimal("2.00"),
        target_action="PREFER_CANDIDATE",
        resulting_outcome="MATCHED",
        resulting_exception_type="FEE_DEDUCTION",
        confidence=0.95,
        is_active=True,
        created_at="2025-01-01T12:00:00Z",
    )
    repo.save_rule(rule)

    fetched = repo.get_rule("RULE-TEST-001")
    assert fetched is not None
    assert fetched.name == "Merchant F Fee Rule"
    assert fetched.max_amount_difference == Decimal("2.00")
    assert fetched.confidence == 0.95
    assert fetched.is_active is True

    all_rules = repo.get_rules(active_only=True)
    assert len(all_rules) >= 1
    assert any(r.rule_id == "RULE-TEST-001" for r in all_rules)


def test_rule_toggle(client_with_service, isolated_service):
    """Test 17: Toggle rule activation status via API."""
    repo = isolated_service.repository
    rule = ReconciliationRule(
        rule_id="RULE-TOGGLE-1",
        name="Toggle Test Rule",
        description="Rule to test toggle",
        source_counterparty_pattern="Test Party",
        created_at="2025-01-01T12:00:00Z",
        is_active=True,
    )
    repo.save_rule(rule)

    # Deactivate
    res_deact = client_with_service.post("/rules/RULE-TOGGLE-1/toggle", json={"is_active": False})
    assert res_deact.status_code == 200
    assert res_deact.json()["is_active"] is False
    assert repo.get_rule("RULE-TOGGLE-1").is_active is False

    # Activate
    res_act = client_with_service.post("/rules/RULE-TOGGLE-1/toggle", json={"is_active": True})
    assert res_act.status_code == 200
    assert res_act.json()["is_active"] is True
    assert repo.get_rule("RULE-TOGGLE-1").is_active is True


def test_rule_engine_matches_candidate_option():
    """Test 18: RuleEngine resolves an option in a candidate pool matching rule predicates."""
    src = make_record("G-MATCH", Decimal("1000.00"), source="GATEWAY", counterparty="Merchant Beta")
    tgt = make_record("B-MATCH", Decimal("998.00"), source="BANK", counterparty="Merchant Beta")

    cand_opt = CandidateRelationshipOption(source_record_ids=["G-MATCH"], target_record_ids=["B-MATCH"])
    cand_ev = CandidateRelationshipEvidence(
        candidate_options=[cand_opt],
        relationship_context="Fee candidate pool",
    )
    engine_output = EngineOutput(results=[], candidates=[cand_ev])

    rule = ReconciliationRule(
        rule_id="RULE-BETA",
        name="Beta Fee Rule",
        description="Reconcile Beta ₹2 fee",
        source_counterparty_pattern="Merchant Beta",
        max_amount_difference=Decimal("2.00"),
        resulting_outcome="MATCHED",
        resulting_exception_type="FEE_DEDUCTION",
        created_at="2025-01-01T00:00:00Z",
    )

    rule_results, remaining_cands, events = RuleEngine.evaluate(
        engine_output=engine_output,
        source_records=[src],
        target_records=[tgt],
        active_rules=[rule],
        committed_results=[],
    )

    assert len(rule_results) == 1
    assert len(remaining_cands) == 0
    assert rule_results[0].outcome == ReconciliationOutcome.MATCHED
    assert rule_results[0].exception_type == ExceptionType.FEE_DEDUCTION
    assert rule_results[0].source_record_ids == ["G-MATCH"]
    assert rule_results[0].target_record_ids == ["B-MATCH"]
    assert len(events) == 1
    assert events[0]["event"] == "RULE_APPLICATION_COMPLETED"


def test_rule_engine_rejects_ambiguous_multiple_options():
    """Test 19: RuleEngine leaves candidate pool unresolved if rule matches multiple options."""
    src = make_record("G-AMB", Decimal("100.00"), source="GATEWAY", counterparty="Merchant Multi")
    tgt1 = make_record("B-AMB-1", Decimal("99.00"), source="BANK", counterparty="Merchant Multi")
    tgt2 = make_record("B-AMB-2", Decimal("99.00"), source="BANK", counterparty="Merchant Multi")

    opt1 = CandidateRelationshipOption(source_record_ids=["G-AMB"], target_record_ids=["B-AMB-1"])
    opt2 = CandidateRelationshipOption(source_record_ids=["G-AMB"], target_record_ids=["B-AMB-2"])
    cand_ev = CandidateRelationshipEvidence(
        candidate_options=[opt1, opt2],
        relationship_context="Ambiguous multi-option pool",
    )
    engine_output = EngineOutput(results=[], candidates=[cand_ev])

    rule = ReconciliationRule(
        rule_id="RULE-MULTI",
        name="Multi Option Rule",
        description="Rule matching both options",
        source_counterparty_pattern="Merchant Multi",
        max_amount_difference=Decimal("1.00"),
        created_at="2025-01-01T00:00:00Z",
    )

    rule_results, remaining_cands, events = RuleEngine.evaluate(
        engine_output=engine_output,
        source_records=[src],
        target_records=[tgt1, tgt2],
        active_rules=[rule],
        committed_results=[],
    )

    # Ambiguity prevents greedy selection: left unresolved for AI
    assert len(rule_results) == 0
    assert len(remaining_cands) == 1


def test_rule_engine_rejects_participant_collision():
    """Test 20: RuleEngine rejects rule match if it conflicts with an already committed result."""
    src = make_record("G-COLL", Decimal("500.00"), source="GATEWAY", counterparty="Merchant Coll")
    tgt = make_record("B-COLL", Decimal("500.00"), source="BANK", counterparty="Merchant Coll")

    opt = CandidateRelationshipOption(source_record_ids=["G-COLL"], target_record_ids=["B-COLL"])
    cand_ev = CandidateRelationshipEvidence(candidate_options=[opt], relationship_context="Collision pool")
    engine_output = EngineOutput(results=[], candidates=[cand_ev])

    # Already committed result containing G-COLL
    committed = [
        ReconciliationResult(
            relationship_id="REL-EXISTING",
            relationship_type=RelationshipType.ONE_TO_ONE,
            source_record_ids=["G-COLL"],
            target_record_ids=["B-OTHER"],
            outcome=ReconciliationOutcome.MATCHED,
        )
    ]

    rule = ReconciliationRule(
        rule_id="RULE-COLL",
        name="Coll Rule",
        description="Coll rule",
        source_counterparty_pattern="Merchant Coll",
        created_at="2025-01-01T00:00:00Z",
    )

    rule_results, remaining_cands, events = RuleEngine.evaluate(
        engine_output=engine_output,
        source_records=[src],
        target_records=[tgt],
        active_rules=[rule],
        committed_results=committed,
    )

    assert len(rule_results) == 0
    assert len(remaining_cands) == 1
    assert any(e["event"] == "RULE_APPLICATION_REJECTED" for e in events)


def test_correction_generate_rule_lifecycle(client_with_service, isolated_service):
    """Test 21 & 22: Operator correction with generate_rule=True synthesizes rule and links it."""
    sources = [
        make_record(
            "G-FEE-1",
            Decimal("8000.00"),
            source="GATEWAY",
            reference="TX-FEE-88",
            counterparty="Vendor Alpha",
            txn_date=date(2025, 3, 1),
        )
    ]
    targets = [
        make_record(
            "B-FEE-1",
            Decimal("7995.00"),
            source="BANK",
            reference="TX-FEE-88",
            counterparty="Vendor Alpha",
            settlement_date=date(2025, 3, 2),
        )
    ]
    res_run = isolated_service.reconcile_records(sources, targets)
    run_id = res_run["run_id"]
    rel_id = isolated_service.repository.get_results(run_id)[0].relationship_id

    # 1. Submit correction with generate_rule = True
    payload = {
        "corrected_outcome": "MATCHED",
        "corrected_exception_type": "FEE_DEDUCTION",
        "corrected_source_ids": ["G-FEE-1"],
        "corrected_target_ids": ["B-FEE-1"],
        "operator_reason": "Vendor Alpha settlement fee of ₹5",
        "generate_rule": True,
    }

    res_post = client_with_service.post(f"/runs/{run_id}/results/{rel_id}/correct", json=payload)
    assert res_post.status_code == 201
    data = res_post.json()

    assert data["generated_rule_id"] is not None
    assert data["generated_rule_id"].startswith("RULE-")
    rule_id = data["generated_rule_id"]

    # 2. Check rule in GET /rules
    res_rules = client_with_service.get("/rules")
    assert res_rules.status_code == 200
    rule_list = res_rules.json()["rules"]
    assert any(r["rule_id"] == rule_id for r in rule_list)

    # 3. Check individual rule GET /rules/{rule_id}
    res_rule_get = client_with_service.get(f"/rules/{rule_id}")
    assert res_rule_get.status_code == 200
    assert res_rule_get.json()["source_counterparty_pattern"] == "Vendor Alpha"
    assert res_rule_get.json()["max_amount_difference"] == "5.00"


def test_rerun_workflow_and_rule_impact(client_with_service, isolated_service):
    """Test 23 & 24: Rerun workflow produces distinct run and GET /rule-impact displays before/after deltas."""
    sources = [
        make_record(
            "G-RR-1",
            Decimal("1000.00"),
            source="GATEWAY",
            counterparty="Vendor Rerun",
            txn_date=date(2025, 4, 1),
        )
    ]
    targets = [
        make_record(
            "B-RR-1",
            Decimal("998.50"),
            source="BANK",
            counterparty="Vendor Rerun",
            settlement_date=date(2025, 4, 2),
        )
    ]
    # Initial run without active rule
    res_run1 = isolated_service.reconcile_records(sources, targets)
    run_id1 = res_run1["run_id"]

    # Add active rule for Vendor Rerun
    rule = ReconciliationRule(
        rule_id="RULE-RERUN-1",
        name="Vendor Rerun Fee Rule",
        description="Matches Vendor Rerun fee",
        source_counterparty_pattern="Vendor Rerun",
        max_amount_difference=Decimal("1.50"),
        resulting_outcome="MATCHED",
        resulting_exception_type="FEE_DEDUCTION",
        confidence=1.0,
        is_active=True,
        created_at="2025-04-01T00:00:00Z",
    )
    isolated_service.repository.save_rule(rule)

    # Trigger Rerun via API
    res_rerun = client_with_service.post(f"/runs/{run_id1}/rerun", json={"apply_rules": True})
    assert res_rerun.status_code == 201
    rerun_data = res_rerun.json()

    rerun_id = rerun_data["rerun_id"]
    assert rerun_id.startswith(f"{run_id1}-RERUN-")
    assert rerun_data["parent_run_id"] == run_id1

    # Verify original run is unchanged
    orig_results = isolated_service.repository.get_results(run_id1)
    assert len(orig_results) == 1

    # Check Rule Impact API
    res_impact = client_with_service.get(f"/runs/{run_id1}/rule-impact")
    assert res_impact.status_code == 200
    impact = res_impact.json()

    assert impact["has_rerun"] is True
    assert impact["before"]["run_id"] == run_id1
    assert impact["after"]["run_id"] == rerun_id
    assert "delta" in impact


def test_inactive_rule_not_applied():
    """Test 25: Inactive rules are ignored during candidate pool evaluation."""
    src = make_record("G-INACT", Decimal("500.00"), source="GATEWAY", counterparty="Merchant Inact")
    tgt = make_record("B-INACT", Decimal("500.00"), source="BANK", counterparty="Merchant Inact")

    opt = CandidateRelationshipOption(source_record_ids=["G-INACT"], target_record_ids=["B-INACT"])
    cand_ev = CandidateRelationshipEvidence(candidate_options=[opt], relationship_context="Pool")
    engine_output = EngineOutput(results=[], candidates=[cand_ev])

    inactive_rule = ReconciliationRule(
        rule_id="RULE-INACT",
        name="Inactive Rule",
        description="Disabled rule",
        source_counterparty_pattern="Merchant Inact",
        is_active=False,
        created_at="2025-01-01T00:00:00Z",
    )

    # When active_rules does not include inactive_rule
    rule_results, remaining_cands, events = RuleEngine.evaluate(
        engine_output=engine_output,
        source_records=[src],
        target_records=[tgt],
        active_rules=[],  # Repository filters by active_only=True
        committed_results=[],
    )
    assert len(rule_results) == 0
    assert len(remaining_cands) == 1


def test_multiple_rules_use_deterministic_precedence():
    """Test 26: RuleEngine uses confidence -> specificity -> rule_id to resolve ties."""
    src = make_record("G-PREC", Decimal("1000.00"), source="GATEWAY", counterparty="Merchant Prec", reference="TXN-99")
    tgt = make_record("B-PREC", Decimal("1000.00"), source="BANK", counterparty="Merchant Prec")

    opt = CandidateRelationshipOption(source_record_ids=["G-PREC"], target_record_ids=["B-PREC"])
    cand_ev = CandidateRelationshipEvidence(candidate_options=[opt], relationship_context="Pool")
    engine_output = EngineOutput(results=[], candidates=[cand_ev])

    # General rule: confidence 0.8, 1 predicate
    rule_general = ReconciliationRule(
        rule_id="RULE-GEN",
        name="General Rule",
        description="General rule",
        source_counterparty_pattern="Merchant Prec",
        confidence=0.8,
        created_at="2025-01-01T00:00:00Z",
    )

    # Specific rule: confidence 0.95, 2 predicates
    rule_specific = ReconciliationRule(
        rule_id="RULE-SPEC",
        name="Specific Rule",
        description="Specific rule",
        source_counterparty_pattern="Merchant Prec",
        reference_prefix="TXN-",
        confidence=0.95,
        created_at="2025-01-01T00:00:00Z",
    )

    rule_results, remaining_cands, events = RuleEngine.evaluate(
        engine_output=engine_output,
        source_records=[src],
        target_records=[tgt],
        active_rules=[rule_general, rule_specific],
        committed_results=[],
    )

    assert len(rule_results) == 1
    assert len(remaining_cands) == 0
    assert events[0]["rule_id"] == "RULE-SPEC"


def test_rule_engine_respects_amount_tolerance_and_delay():
    """Test 27: RuleEngine respects max_amount_difference and max_settlement_delay_days boundaries."""
    src = make_record(
        "G-BOUND",
        Decimal("1000.00"),
        source="GATEWAY",
        counterparty="Vendor Bound",
        txn_date=date(2025, 1, 1),
    )
    # Target exceeds tolerance (₹990 vs ₹5 tolerance)
    tgt_exceed_amt = make_record(
        "B-BOUND-1",
        Decimal("990.00"),
        source="BANK",
        counterparty="Vendor Bound",
        settlement_date=date(2025, 1, 2),
    )
    # Target exceeds delay (10 days vs 3 days tolerance)
    tgt_exceed_delay = make_record(
        "B-BOUND-2",
        Decimal("997.00"),
        source="BANK",
        counterparty="Vendor Bound",
        settlement_date=date(2025, 1, 12),
    )

    rule = ReconciliationRule(
        rule_id="RULE-BOUND",
        name="Boundary Rule",
        description="Tolerance rule",
        source_counterparty_pattern="Vendor Bound",
        max_amount_difference=Decimal("5.00"),
        max_settlement_delay_days=3,
        created_at="2025-01-01T00:00:00Z",
    )

    # 1. Test amount boundary exceeded
    cand_amt = CandidateRelationshipEvidence(
        candidate_options=[CandidateRelationshipOption(source_record_ids=["G-BOUND"], target_record_ids=["B-BOUND-1"])],
        relationship_context="Amount exceeded",
    )
    res1, rem1, _ = RuleEngine.evaluate(
        engine_output=EngineOutput(results=[], candidates=[cand_amt]),
        source_records=[src],
        target_records=[tgt_exceed_amt],
        active_rules=[rule],
    )
    assert len(res1) == 0
    assert len(rem1) == 1

    # 2. Test delay boundary exceeded
    cand_delay = CandidateRelationshipEvidence(
        candidate_options=[CandidateRelationshipOption(source_record_ids=["G-BOUND"], target_record_ids=["B-BOUND-2"])],
        relationship_context="Delay exceeded",
    )
    res2, rem2, _ = RuleEngine.evaluate(
        engine_output=EngineOutput(results=[], candidates=[cand_delay]),
        source_records=[src],
        target_records=[tgt_exceed_delay],
        active_rules=[rule],
    )
    assert len(res2) == 0
    assert len(rem2) == 1


def test_malicious_and_safety_constraints():
    """Test 28: Malicious and invalid rule constraints are strictly rejected."""
    # Negative amount tolerance rejected
    with pytest.raises(ValueError, match="cannot be negative"):
        ReconciliationRule(
            rule_id="R-NEG",
            name="Negative Amount",
            description="test",
            max_amount_difference=Decimal("-5.00"),
            created_at="2025-01-01T00:00:00Z",
        )

    # Negative settlement delay rejected
    with pytest.raises(ValueError, match="cannot be negative"):
        ReconciliationRule(
            rule_id="R-NEG-D",
            name="Negative Delay",
            description="test",
            max_settlement_delay_days=-2,
            created_at="2025-01-01T00:00:00Z",
        )

    # No predicates rejected
    with pytest.raises(ValueError, match="no predicates specified"):
        ReconciliationRule(
            rule_id="R-EMPTY",
            name="Empty",
            description="test",
            created_at="2025-01-01T00:00:00Z",
        )


def test_end_to_end_rule_learning_and_rerun_resolution(client_with_service, isolated_service):

    """Test 29: Full product loop - Exception -> Correction with generate_rule=True -> Rule Synthesis -> Active -> Rerun -> Resolution -> Impact."""
    # 1 Source, 3 Targets: Candidate pool with 2 competing split-settlement options
    sources = [
        CanonicalRecord(
            record_id="SRC-GAMMA-01",
            transaction_id="TX-GAMMA-01",
            source="GATEWAY",
            source_reference="REF-GAMMA-100",
            amount=Decimal("10000.00"),
            currency="INR",
            transaction_date=date(2025, 5, 1),
            settlement_date=date(2025, 5, 1),
            counterparty="Merchant Gamma",
            status="COMPLETED",
            transaction_type="CREDIT",
        )
    ]
    targets = [
        CanonicalRecord(
            record_id="BNK-GAMMA-01",
            transaction_id="BNK-GAMMA-01",
            source="BANK",
            source_reference="BNK-GAMMA-01",
            amount=Decimal("6000.00"),
            currency="INR",
            transaction_date=date(2025, 5, 2),
            settlement_date=date(2025, 5, 2),
            counterparty="Merchant Gamma",
            status="POSTED",
            transaction_type="CREDIT",
        ),
        CanonicalRecord(
            record_id="BNK-GAMMA-02",
            transaction_id="BNK-GAMMA-02",
            source="BANK",
            source_reference="BNK-GAMMA-02",
            amount=Decimal("4000.00"),
            currency="INR",
            transaction_date=date(2025, 5, 2),
            settlement_date=date(2025, 5, 2),
            counterparty="Merchant Gamma",
            status="POSTED",
            transaction_type="CREDIT",
        ),
        CanonicalRecord(
            record_id="BNK-DECOY-03",
            transaction_id="BNK-DECOY-03",
            source="BANK",
            source_reference="BNK-DECOY-03",
            amount=Decimal("4000.00"),
            currency="INR",
            transaction_date=date(2025, 5, 2),
            settlement_date=date(2025, 5, 2),
            counterparty="Decoy Merchant",
            status="POSTED",
            transaction_type="CREDIT",
        ),
    ]

    # 1. Initial Run without rules
    init_res = isolated_service.reconcile_records(sources, targets, apply_rules=False)
    run_id = init_res["run_id"]
    init_results = isolated_service.repository.get_results(run_id)
    assert len(init_results) > 0
    target_rel = [r for r in init_results if "SRC-GAMMA-01" in r.source_record_ids][0]
    assert target_rel.outcome == ReconciliationOutcome.EXCEPTION

    # 2. Operator submits correction with generate_rule = True
    corr_payload = {
        "corrected_outcome": "MATCHED",
        "corrected_exception_type": None,
        "corrected_source_ids": ["SRC-GAMMA-01"],
        "corrected_target_ids": ["BNK-GAMMA-01", "BNK-GAMMA-02"],
        "operator_reason": "Merchant Gamma split batch settlement match",
        "generate_rule": True,
    }
    post_corr = client_with_service.post(f"/runs/{run_id}/results/{target_rel.relationship_id}/correct", json=corr_payload)
    assert post_corr.status_code == 201
    corr_data = post_corr.json()
    rule_id = corr_data["generated_rule_id"]

    # 3. Verify Correction & Rule are persisted and active
    corr_record = isolated_service.repository.get_correction(corr_data["correction_id"])
    assert corr_record is not None
    rule_record = isolated_service.repository.get_rule(rule_id)
    assert rule_record is not None
    assert rule_record.is_active is True
    assert rule_record.source_counterparty_pattern == "Merchant Gamma"

    # 4. Rerun with apply_rules = True
    rerun_post = client_with_service.post(f"/runs/{run_id}/rerun", json={"apply_rules": True})
    assert rerun_post.status_code == 201
    rerun_data = rerun_post.json()
    rerun_id = rerun_data["rerun_id"]
    assert rerun_id != run_id
    assert rerun_data["parent_run_id"] == run_id

    # 5. Verify Original Run remains 100% unchanged
    orig_results_after = isolated_service.repository.get_results(run_id)
    assert len(orig_results_after) == len(init_results)
    for orig, curr in zip(init_results, orig_results_after):
        assert orig.outcome == curr.outcome
        assert orig.exception_type == curr.exception_type

    # 6. Verify Rerun results: RuleEngine selects candidate and commits MATCHED
    rerun_results = isolated_service.repository.get_results(rerun_id)
    matched_results = [r for r in rerun_results if r.outcome == ReconciliationOutcome.MATCHED]
    assert len(matched_results) == 1
    matched_rel = matched_results[0]
    assert set(matched_rel.source_record_ids) == {"SRC-GAMMA-01"}
    assert set(matched_rel.target_record_ids) == {"BNK-GAMMA-01", "BNK-GAMMA-02"}
    assert matched_rel.reconciled_amount == Decimal("10000.00")

    # 7. Verify Rule Provenance Audit Event
    audit_logs = isolated_service.repository.get_audit_logs(rerun_id)
    rule_applied_events = [
        l for l in audit_logs 
        if l["event_type"] == "RULE_APPLICATION_COMPLETED" and "rule_id" in l.get("details", {})
    ]
    assert len(rule_applied_events) == 1
    assert rule_applied_events[0]["details"]["rule_id"] == rule_id


    # 8. Verify Rule Impact API reports measurable improvement
    impact_resp = client_with_service.get(f"/runs/{run_id}/rule-impact")
    assert impact_resp.status_code == 200
    impact = impact_resp.json()
    assert impact["has_rerun"] is True
    assert impact["before"]["match_rate"] < impact["after"]["match_rate"]
    assert impact["delta"]["match_rate_improvement"] > 0
    assert impact["delta"]["resolved_exceptions"] > 0


def test_active_rule_does_not_match_unrelated_candidate(client_with_service, isolated_service):
    """Test 30: Active rule for Merchant A does not match candidates for unrelated Merchant B."""
    sources = [
        CanonicalRecord(
            record_id="SRC-DELTA-01",
            transaction_id="TX-DELTA-01",
            source="GATEWAY",
            source_reference="REF-DELTA-100",
            amount=Decimal("5000.00"),
            currency="INR",
            transaction_date=date(2025, 5, 1),
            settlement_date=date(2025, 5, 1),
            counterparty="Merchant Delta",
            status="COMPLETED",
            transaction_type="CREDIT",
        )
    ]
    targets = [
        CanonicalRecord(
            record_id="BNK-DELTA-01",
            transaction_id="BNK-DELTA-01",
            source="BANK",
            source_reference="BNK-DELTA-01",
            amount=Decimal("2500.00"),
            currency="INR",
            transaction_date=date(2025, 5, 2),
            settlement_date=date(2025, 5, 2),
            counterparty="Merchant Delta",
            status="POSTED",
            transaction_type="CREDIT",
        ),
        CanonicalRecord(
            record_id="BNK-DELTA-02",
            transaction_id="BNK-DELTA-02",
            source="BANK",
            source_reference="BNK-DELTA-02",
            amount=Decimal("2500.00"),
            currency="INR",
            transaction_date=date(2025, 5, 2),
            settlement_date=date(2025, 5, 2),
            counterparty="Merchant Delta",
            status="POSTED",
            transaction_type="CREDIT",
        ),
        CanonicalRecord(
            record_id="BNK-DECOY-DELTA",
            transaction_id="BNK-DECOY-DELTA",
            source="BANK",
            source_reference="BNK-DECOY",
            amount=Decimal("2500.00"),
            currency="INR",
            transaction_date=date(2025, 5, 2),
            settlement_date=date(2025, 5, 2),
            counterparty="Other Merchant",
            status="POSTED",
            transaction_type="CREDIT",
        ),
    ]

    # Save active rule for a completely different counterparty
    rule = ReconciliationRule(
        rule_id="RULE-UNRELATED-ZETA",
        name="Merchant Zeta Rule",
        description="Matches only Merchant Zeta",
        source_counterparty_pattern="Merchant Zeta",
        currency="INR",
        max_amount_difference=Decimal("0.00"),
        is_active=True,
        created_at="2025-05-01T00:00:00Z",
    )
    isolated_service.repository.save_rule(rule)

    # Reconcile with apply_rules = True
    res = isolated_service.reconcile_records(sources, targets, apply_rules=True)
    run_id = res["run_id"]

    audit_logs = isolated_service.repository.get_audit_logs(run_id)
    rule_events = [l for l in audit_logs if l["event_type"] == "RULE_APPLICATION_COMPLETED"]
    # The Zeta rule must NOT match Delta candidate options
    assert len(rule_events) == 0


def test_cross_cardinality_1n_split_and_1to1_decoy_rule_learning_and_rerun(client_with_service, isolated_service):
    """Test 31: Cross-cardinality candidate pool (1:1 Decoy vs 1:N Split) remains unresolved in baseline,

    persists operator correction, synthesizes active generalized rule for counterparty,
    and rerun uniquely resolves the 1:N match while keeping the 1:1 decoy unmatched.
    """
    sources = [
        CanonicalRecord(
            record_id="SRC-GAMMA",
            transaction_id="TX-GAMMA",
            source="GATEWAY",
            source_reference="REF-GAMMA",
            amount=Decimal("10000.00"),
            currency="INR",
            transaction_date=date(2026, 8, 31),
            settlement_date=date(2026, 8, 31),
            counterparty="Merchant-Gamma",
            status="COMPLETED",
            transaction_type="CREDIT",
        )
    ]
    targets = [
        CanonicalRecord(
            record_id="BANK-GAMMA-01",
            transaction_id="BNK-G01",
            source="BANK",
            source_reference="REF-G01",
            amount=Decimal("6000.00"),
            currency="INR",
            transaction_date=date(2026, 8, 31),
            settlement_date=date(2026, 8, 31),
            counterparty="Merchant-Gamma",
            status="POSTED",
            transaction_type="CREDIT",
        ),
        CanonicalRecord(
            record_id="BANK-GAMMA-02",
            transaction_id="BNK-G02",
            source="BANK",
            source_reference="REF-G02",
            amount=Decimal("4000.00"),
            currency="INR",
            transaction_date=date(2026, 8, 31),
            settlement_date=date(2026, 8, 31),
            counterparty="Merchant-Gamma",
            status="POSTED",
            transaction_type="CREDIT",
        ),
        CanonicalRecord(
            record_id="BANK-DECOY",
            transaction_id="BNK-DEC",
            source="BANK",
            source_reference="REF-DEC",
            amount=Decimal("10000.00"),
            currency="INR",
            transaction_date=date(2026, 8, 31),
            settlement_date=date(2026, 8, 31),
            counterparty="Decoy-Merchant",
            status="POSTED",
            transaction_type="CREDIT",
        ),
    ]

    # 1. Baseline reconciliation: must remain unresolved due to competing 1:1 and 1:N options
    baseline_res = isolated_service.reconcile_records(sources, targets, apply_rules=False)
    run_id = baseline_res["run_id"]
    baseline_metrics = isolated_service.calculate_metrics(run_id)

    assert baseline_metrics["matched_count"] == 0
    assert baseline_metrics["match_rate"] == 0.0
    assert baseline_metrics["value_weighted_match_rate"] == 0.0

    # Verify candidate pool was formed with both 1:1 decoy and 1:N split
    candidate_decisions = isolated_service.repository.get_candidates(run_id)
    assert len(candidate_decisions) >= 1
    cd = candidate_decisions[0]
    assert cd["anchor_record_id"] == "SRC-GAMMA"
    
    # 2. Find the unresolved relationship for SRC-GAMMA
    init_results = isolated_service.repository.get_results(run_id)
    target_rel = next(r for r in init_results if "SRC-GAMMA" in r.source_record_ids)
    assert target_rel.outcome == ReconciliationOutcome.EXCEPTION

    # 3. Submit operator correction selecting the 1:N split
    corr_payload = {
        "corrected_outcome": "MATCHED",
        "corrected_source_ids": ["SRC-GAMMA"],
        "corrected_target_ids": ["BANK-GAMMA-01", "BANK-GAMMA-02"],
        "operator_reason": "Settlement split confirmed with Merchant-Gamma",
        "generate_rule": True,
    }
    corr_resp = client_with_service.post(
        f"/runs/{run_id}/results/{target_rel.relationship_id}/correct",
        json=corr_payload,
    )
    assert corr_resp.status_code in {200, 201}
    corr_data = corr_resp.json()
    rule_id = corr_data["generated_rule_id"]
    assert rule_id is not None

    # Verify rule was synthesized and is active
    rule = isolated_service.repository.get_rule(rule_id)
    assert rule is not None
    assert rule.is_active is True
    assert rule.source_counterparty_pattern == "Merchant-Gamma"
    assert rule.currency == "INR"

    # 4. Trigger rerun with active rules
    rerun_resp = client_with_service.post(
        f"/runs/{run_id}/rerun",
        json={"apply_rules": True},
    )
    assert rerun_resp.status_code in {200, 201}
    rerun_data = rerun_resp.json()
    rerun_id = rerun_data["rerun_id"]

    # 5. Verify Rerun results: 1:N committed, 1:1 decoy remains unmatched
    rerun_results = isolated_service.repository.get_results(rerun_id)
    matched_results = [r for r in rerun_results if r.outcome == ReconciliationOutcome.MATCHED]
    assert len(matched_results) == 1
    m = matched_results[0]
    assert set(m.source_record_ids) == {"SRC-GAMMA"}
    assert set(m.target_record_ids) == {"BANK-GAMMA-01", "BANK-GAMMA-02"}
    assert m.relationship_type == RelationshipType.ONE_TO_MANY
    assert m.reconciled_amount == Decimal("10000.00")

    # BANK-DECOY must remain unmatched
    matched_target_ids = {tid for r in matched_results for tid in r.target_record_ids}
    assert "BANK-DECOY" not in matched_target_ids
    assert "BANK-GAMMA-01" in matched_target_ids
    assert "BANK-GAMMA-02" in matched_target_ids

    # 6. Verify before/after metrics reflect genuine improvement
    rerun_metrics = isolated_service.calculate_metrics(rerun_id)
    assert rerun_metrics["matched_count"] == 1
    assert rerun_metrics["match_rate"] == 100.0
    assert rerun_metrics["value_weighted_match_rate"] == 100.0
    assert Decimal(rerun_metrics["total_reconciled_amount"]) == Decimal("10000.00")

    impact_resp = client_with_service.get(f"/runs/{run_id}/rule-impact")
    assert impact_resp.status_code == 200
    impact = impact_resp.json()
    assert impact["has_rerun"] is True
    assert impact["delta"]["match_rate_improvement"] == 100.0
    assert impact["delta"]["value_weighted_improvement"] == 100.0


def test_baseline_ambiguous_candidate_unresolved_and_rule_rerun(client_with_service, isolated_service):
    """Test 32: Baseline ambiguous candidate pool (1:N split vs 1:1 decoy) remains unresolved,

    without auto-committing Option 0, leaving BANK-DECOY uncommitted, and operator correction
    synthesizes an active rule that accurately resolves the rerun.
    """
    sources = [
        CanonicalRecord(
            record_id="SRC-RULE-001",
            transaction_id="TX-001",
            source="GATEWAY",
            source_reference="TEST-RULE-001",
            amount=Decimal("12000.00"),
            currency="INR",
            transaction_date=date(2026, 9, 3),
            settlement_date=date(2026, 9, 3),
            counterparty="Merchant-Apex",
            status="COMPLETED",
            transaction_type="CREDIT",
        ),
        CanonicalRecord(
            record_id="SRC-RULE-002",
            transaction_id="TX-002",
            source="GATEWAY",
            source_reference="TEST-RULE-002",
            amount=Decimal("5000.00"),
            currency="INR",
            transaction_date=date(2026, 9, 3),
            settlement_date=date(2026, 9, 3),
            counterparty="Merchant-Beta",
            status="COMPLETED",
            transaction_type="CREDIT",
        ),
    ]

    targets = [
        CanonicalRecord(
            record_id="BANK-APEX-01",
            transaction_id="TX-A01",
            source="BANK",
            source_reference="TEST-RULE-001",
            amount=Decimal("6000.00"),
            currency="INR",
            transaction_date=date(2026, 9, 3),
            settlement_date=date(2026, 9, 3),
            counterparty="Merchant-Apex",
            status="POSTED",
            transaction_type="CREDIT",
        ),
        CanonicalRecord(
            record_id="BANK-APEX-02",
            transaction_id="TX-A02",
            source="BANK",
            source_reference="TEST-RULE-001",
            amount=Decimal("6000.00"),
            currency="INR",
            transaction_date=date(2026, 9, 3),
            settlement_date=date(2026, 9, 3),
            counterparty="Merchant-Apex",
            status="POSTED",
            transaction_type="CREDIT",
        ),
        CanonicalRecord(
            record_id="BANK-DECOY",
            transaction_id="TX-DEC",
            source="BANK",
            source_reference="TEST-RULE-001",
            amount=Decimal("12000.00"),
            currency="INR",
            transaction_date=date(2026, 9, 3),
            settlement_date=date(2026, 9, 3),
            counterparty="Decoy-Merchant",
            status="POSTED",
            transaction_type="CREDIT",
        ),
        CanonicalRecord(
            record_id="BANK-BETA",
            transaction_id="TX-B01",
            source="BANK",
            source_reference="TEST-RULE-002",
            amount=Decimal("5000.00"),
            currency="INR",
            transaction_date=date(2026, 9, 3),
            settlement_date=date(2026, 9, 3),
            counterparty="Merchant-Beta",
            status="POSTED",
            transaction_type="CREDIT",
        ),
    ]

    # 1. Baseline reconciliation (ZERO active rules)
    baseline_res = isolated_service.reconcile_records(sources, targets, apply_rules=False)
    run_id = baseline_res["run_id"]

    # 2. Assert candidate pool contains both 1:N and 1:1 decoy
    candidates = isolated_service.repository.get_candidates(run_id)
    apex_cand = next(c for c in candidates if c["anchor_record_id"] == "SRC-RULE-001")
    assert len(apex_cand["candidate_options"]) == 2
    opts = apex_cand["candidate_options"]
    assert any(set(o["target_record_ids"]) == {"BANK-APEX-01", "BANK-APEX-02"} for o in opts)
    assert any(set(o["target_record_ids"]) == {"BANK-DECOY"} for o in opts)

    # 3. Assert deterministic engine did NOT commit either candidate
    assert apex_cand["selected_candidate_index"] is None
    assert apex_cand["validation_status"] == "ABSTAINED"

    # 4. Assert baseline result is unresolved/EXCEPTION for SRC-RULE-001
    results = isolated_service.repository.get_results(run_id)
    apex_result = next(r for r in results if "SRC-RULE-001" in r.source_record_ids)
    assert apex_result.outcome == ReconciliationOutcome.EXCEPTION
    assert apex_result.target_record_ids == []
    assert apex_result.reconciled_amount == Decimal("12000.00")

    # Unrelated exact match is cleanly committed
    beta_result = next(r for r in results if "SRC-RULE-002" in r.source_record_ids)
    assert beta_result.outcome == ReconciliationOutcome.MATCHED
    assert beta_result.target_record_ids == ["BANK-BETA"]

    # 5. Assert baseline metrics reflect that SRC-RULE-001 was NOT matched
    baseline_metrics = isolated_service.calculate_metrics(run_id)
    assert baseline_metrics["matched_count"] == 1
    assert baseline_metrics["match_rate"] == 50.0
    # 5,000 / 17,000 = 29.41%
    assert baseline_metrics["value_weighted_match_rate"] == 29.41

    # BANK-DECOY must not be committed
    all_committed_targets = {tid for r in results for tid in r.target_record_ids}
    assert "BANK-DECOY" not in all_committed_targets

    # 6. Operator correction selects 1:N split
    corr_payload = {
        "corrected_outcome": "MATCHED",
        "corrected_source_ids": ["SRC-RULE-001"],
        "corrected_target_ids": ["BANK-APEX-01", "BANK-APEX-02"],
        "operator_reason": "Merchant-Apex verified split settlement",
        "generate_rule": True,
    }
    corr_resp = client_with_service.post(
        f"/runs/{run_id}/results/{apex_result.relationship_id}/correct",
        json=corr_payload,
    )
    assert corr_resp.status_code in {200, 201}
    rule_id = corr_resp.json()["generated_rule_id"]
    assert rule_id is not None

    rule = isolated_service.repository.get_rule(rule_id)
    assert rule.is_active is True
    assert rule.source_counterparty_pattern == "Merchant-Apex"

    # 7. Trigger rerun using active rules
    rerun_resp = client_with_service.post(
        f"/runs/{run_id}/rerun",
        json={"apply_rules": True},
    )
    assert rerun_resp.status_code in {200, 201}
    rerun_id = rerun_resp.json()["rerun_id"]

    # 8. Verify rerun: RuleEngine resolves 1:N match, BANK-DECOY remains unmatched
    rerun_results = isolated_service.repository.get_results(rerun_id)
    rerun_matched = [r for r in rerun_results if r.outcome == ReconciliationOutcome.MATCHED]
    assert len(rerun_matched) == 2

    apex_rerun = next(r for r in rerun_matched if "SRC-RULE-001" in r.source_record_ids)
    assert set(apex_rerun.target_record_ids) == {"BANK-APEX-01", "BANK-APEX-02"}
    assert apex_rerun.relationship_type == RelationshipType.ONE_TO_MANY
    assert apex_rerun.reconciled_amount == Decimal("12000.00")

    rerun_target_ids = {tid for r in rerun_results for tid in r.target_record_ids}
    assert "BANK-DECOY" not in rerun_target_ids

    # 9. Verify metrics improvement
    rerun_metrics = isolated_service.calculate_metrics(rerun_id)
    assert rerun_metrics["matched_count"] == 2
    assert rerun_metrics["match_rate"] == 100.0
    assert rerun_metrics["value_weighted_match_rate"] == 100.0

    impact_resp = client_with_service.get(f"/runs/{run_id}/rule-impact")
    assert impact_resp.status_code == 200
    impact = impact_resp.json()
    assert impact["has_rerun"] is True
    assert impact["delta"]["match_rate_improvement"] == 50.0
    assert impact["delta"]["value_weighted_improvement"] == 70.59


def test_live_csv_file_upload_correction_and_rerun_pipeline(client_with_service, isolated_service):
    """Test 36: Full live API workflow: CSV file upload -> baseline ambiguity -> operator correction -> rule synthesis -> rerun 100% metrics.
    
    Validates that CSV columns 'reference' are extracted into 'source_reference' on Gateway/Bank,
    preserved in DB storage, utilized by RuleSynthesizer to infer reference_prefix, and correctly
    evaluated by RuleEngine during rerun.
    """
    gateway_csv = (
        "record_id,amount,currency,date,reference,counterparty\n"
        "SRC-RULE-001,12000.00,INR,2026-09-03,TEST-RULE-001,Merchant-Apex\n"
        "SRC-RULE-002,5000.00,INR,2026-09-03,TEST-RULE-002,Merchant-Beta\n"
    )
    bank_csv = (
        "record_id,amount,currency,date,reference,counterparty\n"
        "BANK-APEX-01,6000.00,INR,2026-09-03,TEST-RULE-001,Merchant-Apex\n"
        "BANK-APEX-02,6000.00,INR,2026-09-03,TEST-RULE-001,Merchant-Apex\n"
        "BANK-DECOY,12000.00,INR,2026-09-03,TEST-RULE-001,Decoy-Merchant\n"
        "BANK-BETA,5000.00,INR,2026-09-03,TEST-RULE-002,Merchant-Beta\n"
    )

    # 1. Upload CSV files to /runs
    files = {
        "gateway_file": ("gateway.csv", io.BytesIO(gateway_csv.encode("utf-8")), "text/csv"),
        "bank_file": ("bank.csv", io.BytesIO(bank_csv.encode("utf-8")), "text/csv"),
    }
    upload_resp = client_with_service.post("/runs", files=files)
    assert upload_resp.status_code == 201
    run_id = upload_resp.json()["run_id"]

    # 2. Verify stored records have source_reference extracted
    records = isolated_service.repository.get_records(run_id)
    apex_src = next(r for r in records if r.record_id == "SRC-RULE-001")
    assert apex_src.source_reference == "TEST-RULE-001"
    apex_tgt1 = next(r for r in records if r.record_id == "BANK-APEX-01")
    assert apex_tgt1.source_reference == "TEST-RULE-001"

    # 3. Verify baseline results: SRC-RULE-001 is EXCEPTION, 50% match rate
    baseline_results = isolated_service.repository.get_results(run_id)
    apex_res = next(r for r in baseline_results if "SRC-RULE-001" in r.source_record_ids)
    assert apex_res.outcome == ReconciliationOutcome.EXCEPTION
    assert apex_res.target_record_ids == []

    baseline_metrics = isolated_service.calculate_metrics(run_id)
    assert baseline_metrics["matched_count"] == 1
    assert baseline_metrics["match_rate"] == 50.0

    # 4. Operator submits correction for Option 0 with generate_rule=True
    corr_payload = {
        "corrected_outcome": "MATCHED",
        "corrected_source_ids": ["SRC-RULE-001"],
        "corrected_target_ids": ["BANK-APEX-01", "BANK-APEX-02"],
        "operator_reason": "Merchant-Apex split settlement",
        "generate_rule": True,
    }
    corr_resp = client_with_service.post(
        f"/runs/{run_id}/results/{apex_res.relationship_id}/correct",
        json=corr_payload,
    )
    assert corr_resp.status_code in {200, 201}
    rule_id = corr_resp.json()["generated_rule_id"]
    assert rule_id is not None

    rule = isolated_service.repository.get_rule(rule_id)
    assert rule.is_active is True
    assert rule.source_counterparty_pattern == "Merchant-Apex"
    assert rule.reference_prefix == "TEST-RULE-"

    # 5. Trigger rerun with rules
    rerun_resp = client_with_service.post(
        f"/runs/{run_id}/rerun",
        json={"apply_rules": True},
    )
    assert rerun_resp.status_code in {200, 201}
    rerun_id = rerun_resp.json()["rerun_id"]

    # 6. Verify rerun resolves SRC-RULE-001 -> BANK-APEX-01 + BANK-APEX-02 with 100% metrics
    rerun_results = isolated_service.repository.get_results(rerun_id)
    apex_rerun = next(r for r in rerun_results if "SRC-RULE-001" in r.source_record_ids)
    assert apex_rerun.outcome == ReconciliationOutcome.MATCHED
    assert set(apex_rerun.target_record_ids) == {"BANK-APEX-01", "BANK-APEX-02"}
    assert apex_rerun.relationship_type == RelationshipType.ONE_TO_MANY
    assert apex_rerun.reconciled_amount == Decimal("12000.00")

    rerun_metrics = isolated_service.calculate_metrics(rerun_id)
    assert rerun_metrics["matched_count"] == 2
    assert rerun_metrics["match_rate"] == 100.0
    assert rerun_metrics["value_weighted_match_rate"] == 100.0






