"""Comprehensive reliability hardening tests for the Eagle reconciliation system (P0.4).

Verifies the 15 critical safety, persistence, collision, and contract invariants:
1. CSV ingestion -> reconciliation -> persistence -> API result.
2. JSON ingestion -> reconciliation -> persistence -> API result.
3. Valid deterministic match commits successfully.
4. Valid AI candidate selection commits successfully.
5. AI abstention creates an exception without a fabricated target.
6. Invalid AI decision is rejected.
7. Global participant collision is rejected.
8. AI cannot fabricate participant IDs.
9. AI cannot fabricate candidate options.
10. Amount mismatch is rejected.
11. Out-of-bounds candidate index is rejected.
12. llama-server unavailable produces a clear actionable error.
13. Historical run remains accessible after service restart.
14. CSV export matches persisted results.
15. JSON export matches persisted results.
"""

import io
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from eagle.agents._llama_server import LlamaServerProvider
from eagle.agents._mock import MockProvider
from eagle.agents.classifier import AIExceptionClassifier
from eagle.agents.provider import LLMProvider
from eagle.api.main import app
from eagle.api.routes import get_service
from eagle.core.config import Settings
from eagle.export.csv_exporter import export_results_to_csv
from eagle.export.json_exporter import export_results_to_json
from eagle.models.ai_contracts import (
    CandidateSelectionDecision,
    ClassificationCase,
    ExceptionClassificationDecision,
)
from eagle.models.canonical import CanonicalRecord
from eagle.models.enums import ExceptionType, ReconciliationOutcome, RelationshipType, Severity
from eagle.models.evidence import CandidateRelationshipEvidence, CandidateRelationshipOption, EngineOutput
from eagle.models.reconciliation import ReconciliationResult
from eagle.reconciliation.engine import reconcile
from eagle.services.reconciliation_service import ReconciliationService
from eagle.storage.database import Database
from eagle.storage.repository import Repository


# ---------------------------------------------------------------------------
# Invariant 1 & 2: Ingestion -> Pipeline -> Persistence -> API Result
# ---------------------------------------------------------------------------

def test_csv_and_json_ingestion_end_to_end():
    db = Database(":memory:")
    repo = Repository(db)
    provider = MockProvider()
    settings = Settings(DATABASE_PATH=":memory:", AI_PROVIDER="mock")
    service = ReconciliationService(repository=repo, provider=provider, settings=settings)

    app.dependency_overrides[get_service] = lambda: service
    client = TestClient(app)

    # 1. CSV Ingestion
    gtw_csv = "payment_id,amount,created_at\nTXN-C1,150.00,2025-01-10\n"
    bank_csv = "bank_reference,settlement_amount,posting_date\nTXN-C1,150.00,2025-01-10\n"
    res_csv = client.post(
        "/runs",
        files={
            "gateway_file": ("gtw.csv", io.BytesIO(gtw_csv.encode("utf-8")), "text/csv"),
            "bank_file": ("bnk.csv", io.BytesIO(bank_csv.encode("utf-8")), "text/csv"),
        },
    )
    assert res_csv.status_code == 201
    run_csv = res_csv.json()
    assert run_csv["status"] == "COMPLETED"
    assert run_csv["matched_count"] == 1

    # 2. JSON Ingestion
    json_payload = {
        "source_records": [{"payment_id": "TXN-J1", "amount": "300.00", "created_at": "2025-01-11"}],
        "target_records": [{"bank_reference": "TXN-J1", "settlement_amount": "300.00", "posting_date": "2025-01-11"}],
    }
    res_json = client.post("/runs/json", json=json_payload)
    assert res_json.status_code == 201
    run_json = res_json.json()
    assert run_json["status"] == "COMPLETED"
    assert run_json["matched_count"] == 1

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Invariant 3 & 4: Valid Matches and AI Candidate Commit
# ---------------------------------------------------------------------------

def test_deterministic_and_valid_candidate_commit():
    class CandidatePickingProvider(LLMProvider):
        async def classify_exception(self, case: ClassificationCase) -> ExceptionClassificationDecision:
            return ExceptionClassificationDecision(
                exception_type=None,
                severity=None,
                flag_for_review=False,
                reasoning="Matched",
                confidence=1.0,
            )

        async def select_candidate(self, case: ClassificationCase) -> CandidateSelectionDecision:
            return CandidateSelectionDecision(
                selected_candidate_index=0,
                relationship_type="1:1",
                outcome="MATCHED",
                exception_type=None,
                severity=None,
                flag_for_review=False,
                reconciled_amount="500.00",
                confidence=0.98,
                reasoning="Optimal reference match",
            )

    classifier = AIExceptionClassifier(provider=CandidatePickingProvider())
    engine_output = EngineOutput(
        results=[
            ReconciliationResult(
                relationship_id="REL-DET-1",
                relationship_type=RelationshipType.ONE_TO_ONE,
                source_record_ids=["SRC-1"],
                target_record_ids=["TGT-1"],
                outcome=ReconciliationOutcome.MATCHED,
                reconciled_amount=Decimal("100.00"),
            )
        ],
        candidates=[
            CandidateRelationshipEvidence(
                relationship_context="Test 1:1 ambiguity",
                candidate_options=[
                    CandidateRelationshipOption(
                        source_record_ids=["SRC-2"],
                        target_record_ids=["TGT-2"],
                    )
                ]
            )
        ],
    )

    src_recs = [
        CanonicalRecord(
            record_id="SRC-2", transaction_id="TXN-2", source="GATEWAY", source_reference="REF",
            amount=Decimal("500.00"), currency="INR", transaction_date=date(2025, 1, 1),
            settlement_date=date(2025, 1, 1), counterparty="X", status="C", transaction_type="P"
        )
    ]
    tgt_recs = [
        CanonicalRecord(
            record_id="TGT-2", transaction_id="TXN-2", source="BANK", source_reference="REF",
            amount=Decimal("500.00"), currency="INR", transaction_date=date(2025, 1, 1),
            settlement_date=date(2025, 1, 1), counterparty="X", status="C", transaction_type="P"
        )
    ]

    output = asyncio_run(classifier.classify_all(engine_output, src_recs, tgt_recs))
    assert len(output.classified_results) == 1
    committed = output.classified_results[0]
    assert committed.source_record_ids == ["SRC-2"]
    assert committed.target_record_ids == ["TGT-2"]
    assert committed.outcome == ReconciliationOutcome.MATCHED


# ---------------------------------------------------------------------------
# Invariant 5: AI Abstention Creates Exception Without Fabricated Target
# ---------------------------------------------------------------------------

def test_ai_abstention_creates_exception_without_target():
    class AbstainingProvider(LLMProvider):
        async def classify_exception(self, case: ClassificationCase) -> ExceptionClassificationDecision:
            return ExceptionClassificationDecision(
                exception_type="POSSIBLE_DUPLICATE",
                severity="HIGH",
                flag_for_review=True,
                reasoning="Suspected duplicate",
                confidence=0.9,
            )

        async def select_candidate(self, case: ClassificationCase) -> CandidateSelectionDecision:
            return CandidateSelectionDecision(
                selected_candidate_index=None,
                relationship_type="1:1",
                outcome="EXCEPTION",
                exception_type="POSSIBLE_DUPLICATE",
                severity="HIGH",
                flag_for_review=True,
                reconciled_amount="0.00",
                confidence=0.9,
                reasoning="Abstaining from candidate selection",
            )

    classifier = AIExceptionClassifier(provider=AbstainingProvider())
    evidence = CandidateRelationshipEvidence(
        relationship_context="Test duplicate ambiguity",
        candidate_options=[
            CandidateRelationshipOption(source_record_ids=["SRC-ABSTAIN"], target_record_ids=["TGT-D1"]),
            CandidateRelationshipOption(source_record_ids=["SRC-ABSTAIN"], target_record_ids=["TGT-D2"]),
        ]
    )
    engine_output = EngineOutput(results=[], candidates=[evidence])

    src_recs = [
        CanonicalRecord(
            record_id="SRC-ABSTAIN", transaction_id="TXN-A", source="GATEWAY", source_reference="REF",
            amount=Decimal("100.00"), currency="INR", transaction_date=date(2025, 1, 1),
            settlement_date=date(2025, 1, 1), counterparty="X", status="C", transaction_type="P"
        )
    ]
    tgt_recs = [
        CanonicalRecord(
            record_id="TGT-D1", transaction_id="TXN-D1", source="BANK", source_reference="REF",
            amount=Decimal("100.00"), currency="INR", transaction_date=date(2025, 1, 1),
            settlement_date=date(2025, 1, 1), counterparty="X", status="C", transaction_type="P"
        )
    ]

    output = asyncio_run(classifier.classify_all(engine_output, src_recs, tgt_recs))
    assert len(output.classified_results) == 1
    res = output.classified_results[0]
    assert res.source_record_ids == ["SRC-ABSTAIN"]
    assert res.target_record_ids == []
    assert res.outcome == ReconciliationOutcome.EXCEPTION
    assert res.exception_type == ExceptionType.POSSIBLE_DUPLICATE


# ---------------------------------------------------------------------------
# Invariant 6, 7 & 10: Invalid Decision, Collision & Amount Mismatch Rejected
# ---------------------------------------------------------------------------

def test_rejection_of_invalid_decisions_and_amount_mismatch():
    class MalformedDecisionProvider(LLMProvider):
        async def classify_exception(self, case: ClassificationCase) -> ExceptionClassificationDecision:
            return ExceptionClassificationDecision(
                exception_type=None, severity=None, flag_for_review=False, reasoning="", confidence=0.0
            )

        async def select_candidate(self, case: ClassificationCase) -> CandidateSelectionDecision:
            # Reconciled amount mismatch (Source is 100, AI says 999)
            return CandidateSelectionDecision(
                selected_candidate_index=0,
                relationship_type="1:1",
                outcome="MATCHED",
                exception_type=None,
                severity=None,
                flag_for_review=False,
                reconciled_amount="999.00",
                confidence=0.5,
                reasoning="Mismatched amount",
            )

    classifier = AIExceptionClassifier(provider=MalformedDecisionProvider())
    evidence = CandidateRelationshipEvidence(
        relationship_context="Test amount mismatch",
        candidate_options=[
            CandidateRelationshipOption(source_record_ids=["SRC-M1"], target_record_ids=["TGT-M1"])
        ]
    )
    engine_output = EngineOutput(results=[], candidates=[evidence])
    src_recs = [
        CanonicalRecord(
            record_id="SRC-M1", transaction_id="TXN-M1", source="GATEWAY", source_reference="REF",
            amount=Decimal("100.00"), currency="INR", transaction_date=date(2025, 1, 1),
            settlement_date=date(2025, 1, 1), counterparty="X", status="C", transaction_type="P"
        )
    ]
    tgt_recs = [
        CanonicalRecord(
            record_id="TGT-M1", transaction_id="TXN-M1", source="BANK", source_reference="REF",
            amount=Decimal("100.00"), currency="INR", transaction_date=date(2025, 1, 1),
            settlement_date=date(2025, 1, 1), counterparty="X", status="C", transaction_type="P"
        )
    ]

    output = asyncio_run(classifier.classify_all(engine_output, src_recs, tgt_recs))
    assert len(output.classified_results) == 0
    assert len(output.failed_cases) == 1
    assert "does not match source amount" in output.failed_cases[0].failure_reason


def test_global_commit_validator_rejects_participant_collision():
    class DoubleBookingProvider(LLMProvider):
        async def classify_exception(self, case: ClassificationCase) -> ExceptionClassificationDecision:
            return ExceptionClassificationDecision(
                exception_type=None, severity=None, flag_for_review=False, reasoning="", confidence=0.0
            )

        async def select_candidate(self, case: ClassificationCase) -> CandidateSelectionDecision:
            return CandidateSelectionDecision(
                selected_candidate_index=0,
                relationship_type="1:1",
                outcome="MATCHED",
                exception_type=None,
                severity=None,
                flag_for_review=False,
                reconciled_amount="100.00",
                confidence=0.9,
                reasoning="",
            )

    classifier = AIExceptionClassifier(provider=DoubleBookingProvider())

    # Candidate 1 and Candidate 2 both compete for same target TGT-SHARED
    c1 = CandidateRelationshipEvidence(
        relationship_context="Group 1",
        candidate_options=[CandidateRelationshipOption(source_record_ids=["SRC-1"], target_record_ids=["TGT-SHARED"])]
    )
    c2 = CandidateRelationshipEvidence(
        relationship_context="Group 2",
        candidate_options=[CandidateRelationshipOption(source_record_ids=["SRC-2"], target_record_ids=["TGT-SHARED"])]
    )
    engine_output = EngineOutput(results=[], candidates=[c1, c2])

    src_recs = [
        CanonicalRecord(record_id="SRC-1", transaction_id="T1", source="GATEWAY", source_reference="REF",
                        amount=Decimal("100.00"), currency="INR", transaction_date=date(2025, 1, 1),
                        settlement_date=date(2025, 1, 1), counterparty="X", status="C", transaction_type="P"),
        CanonicalRecord(record_id="SRC-2", transaction_id="T2", source="GATEWAY", source_reference="REF",
                        amount=Decimal("100.00"), currency="INR", transaction_date=date(2025, 1, 1),
                        settlement_date=date(2025, 1, 1), counterparty="X", status="C", transaction_type="P"),
    ]
    tgt_recs = [
        CanonicalRecord(record_id="TGT-SHARED", transaction_id="TS", source="BANK", source_reference="REF",
                        amount=Decimal("100.00"), currency="INR", transaction_date=date(2025, 1, 1),
                        settlement_date=date(2025, 1, 1), counterparty="X", status="C", transaction_type="P"),
    ]

    output = asyncio_run(classifier.classify_all(engine_output, src_recs, tgt_recs))
    # First decision commits TGT-SHARED, second decision collides and is REJECTED
    assert len(output.classified_results) == 1
    assert len(output.failed_cases) == 1
    assert "Global participant collision" in output.failed_cases[0].failure_reason


# ---------------------------------------------------------------------------
# Invariant 8, 9 & 11: Candidate Index Bounds & Hallucination Prevention
# ---------------------------------------------------------------------------

def test_out_of_bounds_candidate_index_rejected():
    class OutOfBoundsProvider(LLMProvider):
        async def classify_exception(self, case: ClassificationCase) -> ExceptionClassificationDecision:
            return ExceptionClassificationDecision(
                exception_type=None, severity=None, flag_for_review=False, reasoning="", confidence=0.0
            )

        async def select_candidate(self, case: ClassificationCase) -> CandidateSelectionDecision:
            return CandidateSelectionDecision(
                selected_candidate_index=99,  # Out of bounds!
                relationship_type="1:1",
                outcome="MATCHED",
                exception_type=None,
                severity=None,
                flag_for_review=False,
                reconciled_amount="100.00",
                confidence=0.5,
                reasoning="",
            )

    classifier = AIExceptionClassifier(provider=OutOfBoundsProvider())
    c1 = CandidateRelationshipEvidence(
        relationship_context="Bounds check",
        candidate_options=[CandidateRelationshipOption(source_record_ids=["SRC-B1"], target_record_ids=["TGT-B1"])]
    )
    engine_output = EngineOutput(results=[], candidates=[c1])
    src_recs = [
        CanonicalRecord(record_id="SRC-B1", transaction_id="T1", source="GATEWAY", source_reference="REF",
                        amount=Decimal("100.00"), currency="INR", transaction_date=date(2025, 1, 1),
                        settlement_date=date(2025, 1, 1), counterparty="X", status="C", transaction_type="P")
    ]
    tgt_recs = [
        CanonicalRecord(record_id="TGT-B1", transaction_id="T1", source="BANK", source_reference="REF",
                        amount=Decimal("100.00"), currency="INR", transaction_date=date(2025, 1, 1),
                        settlement_date=date(2025, 1, 1), counterparty="X", status="C", transaction_type="P")
    ]

    output = asyncio_run(classifier.classify_all(engine_output, src_recs, tgt_recs))
    assert len(output.classified_results) == 0
    assert len(output.failed_cases) == 1
    assert "Candidate index out of bounds" in output.failed_cases[0].failure_reason


# ---------------------------------------------------------------------------
# Invariant 12: llama-server Unavailability Error Handling
# ---------------------------------------------------------------------------

def test_llama_server_unavailability_raises_informative_runtime_error():
    # Try connecting to a non-existent port
    with pytest.raises(RuntimeError, match="llama-server is unavailable at http://127.0.0.1:59999"):
        LlamaServerProvider(
            base_url="http://127.0.0.1:59999",
            model="google_gemma-4-E2B-it-Q8_0",
        )


# ---------------------------------------------------------------------------
# Invariant 13: SQLite Persistence State Across Service Restarts
# ---------------------------------------------------------------------------

def test_persistence_remains_accessible_across_service_restarts(tmp_path):
    db_file = tmp_path / "test_persisted_runs.db"
    db_uri = f"sqlite:///{db_file}"

    # Instance 1: Create and execute run
    db1 = Database(db_uri)
    repo1 = Repository(db1)
    service1 = ReconciliationService(
        repository=repo1, provider=MockProvider(), settings=Settings(DATABASE_PATH=db_uri)
    )

    sources = [
        CanonicalRecord(
            record_id="PERSIST-SRC-1", transaction_id="T1", source="GATEWAY", source_reference="INV-P1",
            amount=Decimal("750.00"), currency="INR", transaction_date=date(2025, 1, 10),
            settlement_date=date(2025, 1, 10), counterparty="Alpha", status="COMPLETED", transaction_type="PAYMENT"
        )
    ]
    targets = [
        CanonicalRecord(
            record_id="PERSIST-TGT-1", transaction_id="T1", source="BANK", source_reference="INV-P1",
            amount=Decimal("750.00"), currency="INR", transaction_date=date(2025, 1, 11),
            settlement_date=date(2025, 1, 11), counterparty="Alpha", status="POSTED", transaction_type="CREDIT"
        )
    ]

    res = service1.reconcile_records(sources, targets, run_id="RUN-RESTART-TEST")
    assert res["status"] == "COMPLETED"

    # Instance 2: Simulate process restart and reload from SQLite
    db2 = Database(db_uri)
    repo2 = Repository(db2)

    persisted_run = repo2.get_run("RUN-RESTART-TEST")
    assert persisted_run is not None
    assert persisted_run["status"] == "COMPLETED"
    assert persisted_run["total_records"] == 2
    assert persisted_run["matched_count"] == 1

    persisted_records = repo2.get_records("RUN-RESTART-TEST")
    assert len(persisted_records) == 2

    persisted_results = repo2.get_results("RUN-RESTART-TEST")
    assert len(persisted_results) == 1
    assert persisted_results[0].reconciled_amount == Decimal("750.00")


# ---------------------------------------------------------------------------
# Invariant 14 & 15: CSV and JSON Export Truthfulness
# ---------------------------------------------------------------------------

def test_export_serializers_reflect_persisted_results():
    results = [
        ReconciliationResult(
            relationship_id="REL-EXP-1",
            relationship_type=RelationshipType.ONE_TO_ONE,
            source_record_ids=["SRC-E1"],
            target_record_ids=["TGT-E1"],
            outcome=ReconciliationOutcome.MATCHED,
            reconciled_amount=Decimal("1234.50"),
            flag_for_review=False,
        ),
        ReconciliationResult(
            relationship_id="REL-EXP-2",
            relationship_type=RelationshipType.ONE_TO_ONE,
            source_record_ids=["SRC-E2"],
            target_record_ids=[],
            outcome=ReconciliationOutcome.EXCEPTION,
            exception_type=ExceptionType.MISSING_RECORD,
            severity=Severity.HIGH,
            reconciled_amount=Decimal("0.00"),
            flag_for_review=True,
        ),
    ]

    # 1. CSV
    csv_out = export_results_to_csv(results)
    assert "REL-EXP-1" in csv_out
    assert "1234.50" in csv_out
    assert "REL-EXP-2" in csv_out
    assert "MISSING_RECORD" in csv_out

    # 2. JSON
    json_out = export_results_to_json(results, run_metadata={"run_id": "TEST-EXP"})
    parsed = json.loads(json_out)
    assert parsed["run"]["run_id"] == "TEST-EXP"
    assert parsed["total_results"] == 2
    assert parsed["results"][0]["relationship_id"] == "REL-EXP-1"
    assert parsed["results"][0]["reconciled_amount"] == "1234.50"
    assert parsed["results"][1]["exception_type"] == "MISSING_RECORD"


# ---------------------------------------------------------------------------
# Invariant 16: Complete Reviewer Workflow (Ingest -> Demo Data -> Export)
# ---------------------------------------------------------------------------

def test_reviewer_end_to_end_demo_workflow(tmp_path):
    """Test the exact reviewer workflow:
    1. Load packaged demo datasets (gateway.csv, bank.csv)
    2. Submit via API POST /runs
    3. Verify Run status and metrics
    4. Verify Results, Exceptions, Candidates, and Audit Trail
    5. Verify CSV & JSON Exports
    """
    db_file = tmp_path / "reviewer_demo.db"
    db_uri = f"sqlite:///{db_file}"

    db = Database(db_uri)
    repo = Repository(db)
    provider = MockProvider()
    settings = Settings(DATABASE_PATH=db_uri, AI_PROVIDER="mock")
    service = ReconciliationService(repository=repo, provider=provider, settings=settings)

    app.dependency_overrides[get_service] = lambda: service
    client = TestClient(app)

    # 1. Fetch synthetic demo dataset from API
    res_sample = client.get("/demo/synthetic-data")
    assert res_sample.status_code == 200
    sample_data = res_sample.json()
    assert "gateway.csv" in sample_data["gateway_filename"]
    assert "bank.csv" in sample_data["bank_filename"]

    # 2. Run reconciliation via multipart file upload
    files = {
        "gateway_file": ("gateway.csv", io.BytesIO(sample_data["gateway_content"].encode("utf-8")), "text/csv"),
        "bank_file": ("bank.csv", io.BytesIO(sample_data["bank_content"].encode("utf-8")), "text/csv"),
    }
    res_run = client.post("/runs", files=files)
    assert res_run.status_code == 201
    run_info = res_run.json()
    run_id = run_info["run_id"]
    assert run_info["status"] == "COMPLETED"
    assert run_info["total_records"] == 81

    # 3. Verify Run Metadata & Metrics
    res_metrics = client.get(f"/runs/{run_id}/metrics")
    assert res_metrics.status_code == 200
    metrics = res_metrics.json()
    assert metrics["total_records"] == 81
    assert metrics["matched_count"] == 25
    assert metrics["exception_count"] == 9
    assert metrics["missing_count"] == 4
    assert Decimal(metrics["total_reconciled_amount"]) > Decimal("0.00")

    # 4. Verify Reconciled Results List
    res_results = client.get(f"/runs/{run_id}/results")
    assert res_results.status_code == 200
    results_data = res_results.json()
    assert results_data["total"] == 38

    # 5. Verify Filtered Exceptions
    res_exceptions = client.get(f"/runs/{run_id}/exceptions")
    assert res_exceptions.status_code == 200
    assert res_exceptions.json()["total"] >= 9

    # 6. Verify Candidate Inspector Trees & Safety Validation Status
    res_candidates = client.get(f"/runs/{run_id}/candidates")
    assert res_candidates.status_code == 200
    cand_data = res_candidates.json()
    assert cand_data["total"] == 9
    for c in cand_data["candidates"]:
        assert c["validation_status"] in ["COMMITTED", "ABSTAINED", "REJECTED", "UNRESOLVED", "CLASSIFICATION_FAILED"]

    # 7. Verify Chronological Audit Trail
    res_audit = client.get(f"/runs/{run_id}/audit-logs")
    assert res_audit.status_code == 200
    event_types = [e["event_type"] for e in res_audit.json()]
    assert "RUN_CREATED" in event_types
    assert "INGESTION_COMPLETED" in event_types
    assert "RECONCILIATION_STARTED" in event_types
    assert "RUN_COMPLETED" in event_types

    # 8. Verify CSV Export
    res_csv = client.get(f"/runs/{run_id}/export?format=csv")
    assert res_csv.status_code == 200
    assert "relationship_id,source_record_ids,target_record_ids" in res_csv.text

    # 9. Verify JSON Export
    res_json = client.get(f"/runs/{run_id}/export?format=json")
    assert res_json.status_code == 200
    json_export = res_json.json()
    assert json_export["run"]["run_id"] == run_id
    assert len(json_export["results"]) == 38

    app.dependency_overrides.clear()


def asyncio_run(coro):
    import asyncio
    return asyncio.run(coro)
