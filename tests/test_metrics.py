"""Comprehensive test suite for value-weighted reconciliation metrics."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from eagle.agents._mock import MockProvider
from eagle.api.main import app
from eagle.api.routes import get_service
from eagle.core.config import Settings
from eagle.models.canonical import CanonicalRecord
from eagle.models.enums import ExceptionType, ReconciliationOutcome, RelationshipType
from eagle.models.reconciliation import ReconciliationResult
from eagle.services.reconciliation_service import ReconciliationService
from eagle.storage.database import Database
from eagle.storage.repository import Repository


@pytest.fixture
def isolated_service():
    """Create an isolated in-memory ReconciliationService with MockProvider."""
    db = Database(":memory:")
    repo = Repository(db)
    provider = MockProvider()
    settings = Settings(DATABASE_PATH=":memory:", AI_PROVIDER="mock")
    return ReconciliationService(repository=repo, provider=provider, settings=settings)


def make_record(
    record_id: str,
    amount: Decimal,
    source: str = "GATEWAY",
    reference: str = "REF",
    counterparty: str = "Counterparty A",
    fee_amount: Decimal | None = None,
    txn_date: date = date(2025, 1, 1),
) -> CanonicalRecord:
    """Helper to construct valid CanonicalRecord instances for tests."""
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


def test_100_percent_value_weighted_reconciliation(isolated_service):
    """Test 1: All source records reconciled yields 100.0% value-weighted match rate."""
    sources = [
        make_record("SRC-1", Decimal("6000.00"), source="GATEWAY", reference="REF-1"),
        make_record("SRC-2", Decimal("4000.00"), source="GATEWAY", reference="REF-2"),
    ]
    targets = [
        make_record("TGT-1", Decimal("6000.00"), source="BANK", reference="REF-1"),
        make_record("TGT-2", Decimal("4000.00"), source="BANK", reference="REF-2"),
    ]

    res = isolated_service.reconcile_records(sources, targets)
    metrics = isolated_service.calculate_metrics(res["run_id"])

    assert metrics["total_records"] == 4
    assert metrics["matched_count"] == 2
    assert metrics["match_rate"] == 100.0
    assert metrics["value_weighted_match_rate"] == 100.0
    assert metrics["total_reconciled_amount"] == "10000.00"


def test_zero_percent_value_weighted_reconciliation(isolated_service):
    """Test 2: No source records reconciled yields 0.0% value-weighted match rate."""
    sources = [
        make_record("SRC-UNMATCHED", Decimal("15000.00"), source="GATEWAY", reference="REF-SRC"),
    ]
    targets = []

    res = isolated_service.reconcile_records(sources, targets)
    metrics = isolated_service.calculate_metrics(res["run_id"])

    assert metrics["matched_count"] == 0
    assert metrics["match_rate"] == 0.0
    assert metrics["value_weighted_match_rate"] == 0.0
    assert metrics["total_reconciled_amount"] == "0.00"


def test_partial_value_weighted_reconciliation(isolated_service):
    """Test 3: Partial reconciliation calculates exact proportion of gross source value."""
    # SRC-A: 6000 (matched), SRC-B: 3000 (matched), SRC-C: 1000 (missing)
    # Total gross = 10000, Reconciled gross = 9000 -> 90.0%
    sources = [
        make_record("SRC-A", Decimal("6000.00"), source="GATEWAY", reference="REF-A"),
        make_record("SRC-B", Decimal("3000.00"), source="GATEWAY", reference="REF-B"),
        make_record("SRC-C", Decimal("1000.00"), source="GATEWAY", reference="REF-C"),
    ]
    targets = [
        make_record("TGT-A", Decimal("6000.00"), source="BANK", reference="REF-A"),
        make_record("TGT-B", Decimal("3000.00"), source="BANK", reference="REF-B"),
    ]

    res = isolated_service.reconcile_records(sources, targets)
    metrics = isolated_service.calculate_metrics(res["run_id"])

    # Record match rate: 2 matched / 3 sources = 66.67%
    assert metrics["match_rate"] == 66.67
    # Value-weighted match rate: 9000 / 10000 = 90.0%
    assert metrics["value_weighted_match_rate"] == 90.0


def test_n_to_1_fee_deduction_uses_gross_source_value(isolated_service):
    """Test 4: N:1 fee deduction uses gross source sum (10000.00), not net target (9998.50)."""
    # Sources: 3000 + 7000 = 10000 gross
    # Target: 9998.50 net (with 1.50 fee)
    sources = [
        make_record("SRC-1", Decimal("3000.00"), source="GATEWAY", reference="MERCHANT-FEE-BATCH", counterparty="Merchant F"),
        make_record("SRC-2", Decimal("7000.00"), source="GATEWAY", reference="MERCHANT-FEE-BATCH", counterparty="Merchant F"),
    ]
    targets = [
        make_record("TGT-NET", Decimal("9998.50"), source="BANK", reference="MERCHANT-FEE-BATCH", fee_amount=Decimal("1.50"), counterparty="Merchant F"),
    ]

    res = isolated_service.reconcile_records(sources, targets)
    metrics = isolated_service.calculate_metrics(res["run_id"])

    # 1 N:1 relationship matched covering all 2 source records -> 100.0%
    assert metrics["value_weighted_match_rate"] == 100.0


def test_1_to_n_aggregation_value_weighting(isolated_service):
    """Test 5: 1:N relationship counts the single gross source record exactly once."""
    # 1 Gateway record of 10000 split across 2 Bank records (4000 + 6000), plus 1 unmatched source of 5000
    sources = [
        make_record("SRC-SPLIT", Decimal("10000.00"), source="GATEWAY", reference="SPLIT-SETTLEMENT", counterparty="Merchant Split"),
        make_record("SRC-OTHER", Decimal("5000.00"), source="GATEWAY", reference="OTHER", counterparty="Other Merchant"),
    ]
    targets = [
        make_record("TGT-P1", Decimal("4000.00"), source="BANK", reference="SPLIT-SETTLEMENT", counterparty="Merchant Split"),
        make_record("TGT-P2", Decimal("6000.00"), source="BANK", reference="SPLIT-SETTLEMENT", counterparty="Merchant Split"),
    ]

    res = isolated_service.reconcile_records(sources, targets)
    metrics = isolated_service.calculate_metrics(res["run_id"])

    # Total source = 15000.00, Reconciled source = 10000.00 -> 66.67%
    assert metrics["value_weighted_match_rate"] == 66.67


def test_multiple_source_records_in_n_to_1(isolated_service):
    """Test 6: Multiple source records in N:1 sum each participant exactly once."""
    sources = [
        make_record("SRC-1", Decimal("1000.00"), source="GATEWAY", reference="BATCH-X", counterparty="BatchCorp"),
        make_record("SRC-2", Decimal("2000.00"), source="GATEWAY", reference="BATCH-X", counterparty="BatchCorp"),
        make_record("SRC-3", Decimal("3000.00"), source="GATEWAY", reference="BATCH-X", counterparty="BatchCorp"),
    ]
    targets = [
        make_record("TGT-COMBINED", Decimal("6000.00"), source="BANK", reference="BATCH-X", counterparty="BatchCorp"),
    ]

    res = isolated_service.reconcile_records(sources, targets)
    metrics = isolated_service.calculate_metrics(res["run_id"])

    assert metrics["value_weighted_match_rate"] == 100.0


def test_multiple_target_records_in_1_to_n(isolated_service):
    """Test 7: Multiple target records in 1:N relationship sum the single source without multiplication."""
    sources = [
        make_record("SRC-SINGLE", Decimal("9000.00"), source="GATEWAY", reference="TRI-SPLIT", counterparty="TriMerchant"),
    ]
    targets = [
        make_record("TGT-1", Decimal("3000.00"), source="BANK", reference="TRI-SPLIT", counterparty="TriMerchant"),
        make_record("TGT-2", Decimal("3000.00"), source="BANK", reference="TRI-SPLIT", counterparty="TriMerchant"),
        make_record("TGT-3", Decimal("3000.00"), source="BANK", reference="TRI-SPLIT", counterparty="TriMerchant"),
    ]

    res = isolated_service.reconcile_records(sources, targets)
    metrics = isolated_service.calculate_metrics(res["run_id"])

    # Numerator is 9000 (not 9000 * 3), Denominator is 9000 -> 100.0%
    assert metrics["value_weighted_match_rate"] == 100.0


def test_duplicate_source_id_defensive_handling(isolated_service):
    """Test 8: Duplicate source references in results do not inflate the value-weighted numerator."""
    run_id = "RUN-TEST-DEFENSIVE"
    isolated_service.repository.create_run(run_id=run_id, status="COMPLETED", total_records=2, source_count=1)

    sources = [
        make_record("SRC-DUP", Decimal("5000.00"), source="GATEWAY", reference="REF"),
    ]
    isolated_service.repository.save_records(run_id, sources)

    # Save duplicate results claiming same source record ID
    results = [
        ReconciliationResult(
            relationship_id="REL-1",
            source_record_ids=["SRC-DUP"],
            target_record_ids=["TGT-1"],
            relationship_type=RelationshipType.ONE_TO_ONE,
            outcome=ReconciliationOutcome.MATCHED,
            reconciled_amount=Decimal("5000.00"),
        ),
        ReconciliationResult(
            relationship_id="REL-2",
            source_record_ids=["SRC-DUP"],
            target_record_ids=["TGT-2"],
            relationship_type=RelationshipType.ONE_TO_ONE,
            outcome=ReconciliationOutcome.MATCHED,
            reconciled_amount=Decimal("5000.00"),
        ),
    ]
    isolated_service.repository.save_results(run_id, results)

    metrics = isolated_service.calculate_metrics(run_id)
    # Total source = 5000.00, Reconciled source = 5000.00 (not 10000.00) -> 100.0%
    assert metrics["value_weighted_match_rate"] == 100.0


def test_missing_records_handling(isolated_service):
    """Test 9: Missing records contribute to denominator only, not numerator."""
    sources = [
        make_record("SRC-MATCHED", Decimal("8000.00"), source="GATEWAY", reference="R1"),
        make_record("SRC-MISSING", Decimal("2000.00"), source="GATEWAY", reference="R2"),
    ]
    targets = [
        make_record("TGT-MATCHED", Decimal("8000.00"), source="BANK", reference="R1"),
    ]

    res = isolated_service.reconcile_records(sources, targets)
    metrics = isolated_service.calculate_metrics(res["run_id"])

    assert metrics["missing_count"] == 1
    assert metrics["matched_count"] == 1
    # 8000 matched out of 10000 total source gross -> 80.0%
    assert metrics["value_weighted_match_rate"] == 80.0


def test_exceptions_handling(isolated_service):
    """Test 10: Unmatched exception relationships contribute to denominator only."""
    run_id = "RUN-EXCEPTION-TEST"
    isolated_service.repository.create_run(run_id=run_id, status="COMPLETED", total_records=2, source_count=2)

    sources = [
        make_record("SRC-1", Decimal("4000.00"), source="GATEWAY"),
        make_record("SRC-2", Decimal("6000.00"), source="GATEWAY"),
    ]
    isolated_service.repository.save_records(run_id, sources)

    # REL-1 is MATCHED, REL-2 is EXCEPTION (unmatched discrepancy)
    results = [
        ReconciliationResult(
            relationship_id="REL-1",
            source_record_ids=["SRC-1"],
            target_record_ids=["TGT-1"],
            relationship_type=RelationshipType.ONE_TO_ONE,
            outcome=ReconciliationOutcome.MATCHED,
            reconciled_amount=Decimal("4000.00"),
        ),
        ReconciliationResult(
            relationship_id="REL-2",
            source_record_ids=["SRC-2"],
            target_record_ids=[],
            relationship_type=RelationshipType.ONE_TO_ONE,
            outcome=ReconciliationOutcome.EXCEPTION,
            exception_type=ExceptionType.POSSIBLE_DUPLICATE,
            reconciled_amount=Decimal("0.00"),
        ),
    ]
    isolated_service.repository.save_results(run_id, results)

    metrics = isolated_service.calculate_metrics(run_id)
    # Total source = 10000.00, Reconciled = 4000.00 -> 40.0%
    assert metrics["value_weighted_match_rate"] == 40.0


def test_empty_dataset_zero_denominator(isolated_service):
    """Test 11: Empty run returns 0.0 value_weighted_match_rate without dividing by zero."""
    run_id = "RUN-EMPTY"
    isolated_service.repository.create_run(run_id=run_id, status="COMPLETED", total_records=0, source_count=0)
    isolated_service.repository.save_records(run_id, [])
    isolated_service.repository.save_results(run_id, [])

    metrics = isolated_service.calculate_metrics(run_id)
    assert metrics["match_rate"] == 0.0
    assert metrics["value_weighted_match_rate"] == 0.0


def test_api_metrics_endpoint_serialization(isolated_service):
    """Test 12: GET /runs/{run_id}/metrics returns value_weighted_match_rate."""
    app.dependency_overrides[get_service] = lambda: isolated_service
    client = TestClient(app)

    payload = {
        "source_records": [
            {"payment_id": "G-1", "amount": "7500.00", "created_at": "2025-01-01"},
            {"payment_id": "G-2", "amount": "2500.00", "created_at": "2025-01-01"},
        ],
        "target_records": [
            {"bank_reference": "B-1", "settlement_amount": "7500.00", "posting_date": "2025-01-01"},
        ],
    }
    res_run = client.post("/runs/json", json=payload)
    run_id = res_run.json()["run_id"]

    res_metrics = client.get(f"/runs/{run_id}/metrics")
    assert res_metrics.status_code == 200
    data = res_metrics.json()

    # Record match: 1 matched / 2 sources = 50.0%
    assert data["match_rate"] == 50.0
    # Value match: 7500 / 10000 = 75.0%
    assert data["value_weighted_match_rate"] == 75.0
    assert data["total_reconciled_amount"] == "7500.00"


def test_dashboard_and_api_consistency(isolated_service):
    """Test 13: Service calculate_metrics and API return identical values for all fields."""
    app.dependency_overrides[get_service] = lambda: isolated_service
    client = TestClient(app)

    sources = [
        make_record("S-1", Decimal("3000.00"), source="GATEWAY", reference="REF-1"),
        make_record("S-2", Decimal("7000.00"), source="GATEWAY", reference="REF-2"),
    ]
    targets = [
        make_record("T-1", Decimal("3000.00"), source="BANK", reference="REF-1"),
    ]
    res_run = isolated_service.reconcile_records(sources, targets)
    run_id = res_run["run_id"]

    service_metrics = isolated_service.calculate_metrics(run_id)
    api_response = client.get(f"/runs/{run_id}/metrics").json()

    assert service_metrics["match_rate"] == api_response["match_rate"]
    assert service_metrics["value_weighted_match_rate"] == api_response["value_weighted_match_rate"]
    assert service_metrics["total_reconciled_amount"] == api_response["total_reconciled_amount"]


def test_regression_existing_match_rate_unchanged(isolated_service):
    """Test 14: Proves existing record-count match_rate is completely preserved and unchanged."""
    sources = [
        make_record("S1", Decimal("100.00"), source="GATEWAY", reference="R1"),
        make_record("S2", Decimal("900.00"), source="GATEWAY", reference="R2"),
    ]
    targets = [
        make_record("T1", Decimal("100.00"), source="BANK", reference="R1"),
    ]

    res = isolated_service.reconcile_records(sources, targets)
    metrics = isolated_service.calculate_metrics(res["run_id"])

    # 1 out of 2 records matched -> 50.0% record match rate
    assert metrics["match_rate"] == 50.0
    # 100 out of 1000 gross value matched -> 10.0% value-weighted match rate
    assert metrics["value_weighted_match_rate"] == 10.0
