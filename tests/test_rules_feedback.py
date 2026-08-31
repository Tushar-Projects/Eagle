"""Day 1 Unit & Integration Test Suite for Operator Corrections & Persistence."""

from datetime import date
from decimal import Decimal
import uuid

import pytest
from fastapi.testclient import TestClient

from eagle.agents._mock import MockProvider
from eagle.api.main import app
from eagle.api.routes import get_service
from eagle.core.config import Settings
from eagle.models.canonical import CanonicalRecord
from eagle.models.enums import ExceptionType, ReconciliationOutcome, RelationshipType
from eagle.models.reconciliation import ReconciliationResult
from eagle.rules.models import OperatorCorrection
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
    reference: str = "REF",
    counterparty: str = "Merchant X",
    fee_amount: Decimal | None = None,
    txn_date: date = date(2025, 1, 1),
) -> CanonicalRecord:
    """Helper to construct valid CanonicalRecord instances."""
    return CanonicalRecord(
        record_id=record_id,
        transaction_id=record_id,
        source=source,
        source_reference=reference,
        amount=amount,
        currency="INR",
        transaction_date=txn_date,
        settlement_date=txn_date,
        counterparty=counterparty,
        status="COMPLETED" if source == "GATEWAY" else "POSTED",
        transaction_type="CREDIT" if amount >= Decimal("0.00") else "DEBIT",
        fee_amount=fee_amount,
    )


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
    # Setup completed run with records and results
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
        "generate_rule": True,
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

    # Retrieve results again from database
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

    # Fetch corrections list
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

    # Verify both exist in history
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
