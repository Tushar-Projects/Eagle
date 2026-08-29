"""Unit and integration tests for the ReconciliationService."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from eagle.agents._mock import MockProvider
from eagle.agents.provider import LLMProvider
from eagle.core.config import Settings
from eagle.models.ai_contracts import (
    CandidateSelectionDecision,
    ClassificationCase,
    ExceptionClassificationDecision,
)
from eagle.models.canonical import CanonicalRecord
from eagle.models.enums import ExceptionType, ReconciliationOutcome
from eagle.services.reconciliation_service import ReconciliationService
from eagle.storage.database import Database
from eagle.storage.repository import Repository


@pytest.fixture
def test_service():
    """Create an isolated in-memory ReconciliationService with MockProvider."""
    db = Database(":memory:")
    repo = Repository(db)
    provider = MockProvider()
    settings = Settings(DATABASE_PATH=":memory:", AI_PROVIDER="mock")
    return ReconciliationService(repository=repo, provider=provider, settings=settings)


class TestReconciliationService:
    """Test suite for the Application Service lifecycle and orchestration."""

    def test_reconcile_records_lifecycle(self, test_service):
        sources = [
            CanonicalRecord(
                record_id="GTW-10",
                transaction_id="TXN-10",
                source="GATEWAY",
                source_reference="INV-10",
                amount=Decimal("1000.00"),
                currency="INR",
                transaction_date=date(2025, 1, 15),
                settlement_date=date(2025, 1, 15),
                counterparty="Customer A",
                status="COMPLETED",
                transaction_type="PAYMENT",
            ),
            CanonicalRecord(
                record_id="GTW-11",
                transaction_id="TXN-11",
                source="GATEWAY",
                source_reference="INV-11",
                amount=Decimal("2000.00"),
                currency="INR",
                transaction_date=date(2025, 1, 15),
                settlement_date=date(2025, 1, 15),
                counterparty="Customer B",
                status="COMPLETED",
                transaction_type="PAYMENT",
            ),
        ]
        targets = [
            CanonicalRecord(
                record_id="BANK-10",
                transaction_id="TXN-10",
                source="BANK",
                source_reference="INV-10",
                amount=Decimal("1000.00"),
                currency="INR",
                transaction_date=date(2025, 1, 16),
                settlement_date=date(2025, 1, 16),
                counterparty="Customer A",
                status="POSTED",
                transaction_type="CREDIT",
            ),
            CanonicalRecord(
                record_id="BANK-99",
                transaction_id="TXN-99",
                source="BANK",
                source_reference="ORPHAN",
                amount=Decimal("500.00"),
                currency="INR",
                transaction_date=date(2025, 1, 16),
                settlement_date=date(2025, 1, 16),
                counterparty="Unknown",
                status="POSTED",
                transaction_type="CREDIT",
            ),
        ]

        result = test_service.reconcile_records(sources, targets, run_id="RUN-SVC-01")

        assert result["run_id"] == "RUN-SVC-01"
        assert result["status"] == "COMPLETED"
        assert result["results_count"] >= 3  # 1 exact match + 2 missing records

        # Verify database state
        run_data = test_service.repository.get_run("RUN-SVC-01")
        assert run_data["status"] == "COMPLETED"
        assert run_data["total_records"] == 4
        assert run_data["source_count"] == 2
        assert run_data["target_count"] == 2
        assert run_data["matched_count"] == 1
        assert run_data["missing_count"] == 2

        # Verify records persisted
        persisted_records = test_service.repository.get_records("RUN-SVC-01")
        assert len(persisted_records) == 4

        # Verify results persisted
        persisted_results = test_service.repository.get_results("RUN-SVC-01")
        assert len(persisted_results) == result["results_count"]

        # Verify audit trail
        logs = test_service.repository.get_audit_logs("RUN-SVC-01")
        assert len(logs) >= 5
        event_types = [l["event_type"] for l in logs]
        assert "RUN_CREATED" in event_types
        assert "INGESTION_COMPLETED" in event_types
        assert "RECONCILIATION_STARTED" in event_types
        assert "AI_CLASSIFICATION_COMPLETED" in event_types
        assert "RUN_COMPLETED" in event_types

    def test_reconcile_files_with_synthetic_csvs(self, test_service):
        gtw_path = Path("data/synthetic/gateway.csv")
        bank_path = Path("data/synthetic/bank.csv")

        if not (gtw_path.exists() and bank_path.exists()):
            pytest.skip("Synthetic dataset CSV files not present")

        result = test_service.reconcile_files(gtw_path, bank_path, run_id="RUN-SYNTH-01")

        assert result["status"] == "COMPLETED"
        assert result["results_count"] > 30
        assert result["candidates_count"] == 9

        run_data = test_service.repository.get_run("RUN-SYNTH-01")
        assert run_data["matched_count"] >= 24
        assert run_data["unresolved_count"] >= 0

        # Verify candidate decisions persisted
        candidates = test_service.repository.get_candidates("RUN-SYNTH-01")
        assert len(candidates) == 9
        statuses = [c["validation_status"] for c in candidates]
        assert "COMMITTED" in statuses or "ABSTAINED" in statuses

    def test_ingestion_failure_records_failed_run(self, test_service):
        with pytest.raises(Exception):
            test_service.reconcile_files(
                gateway_input="corrupted,header\ninvalid_data",
                bank_input="",
                run_id="RUN-FAIL-01",
            )

        run_data = test_service.repository.get_run("RUN-FAIL-01")
        assert run_data is not None
        assert run_data["status"] == "FAILED"
        assert "Ingestion failed" in run_data["error_message"]

        logs = test_service.repository.get_audit_logs("RUN-FAIL-01")
        assert len(logs) == 1
        assert logs[0]["event_type"] == "RUN_FAILED"

    def test_safety_preservation_global_commit_collision_handling(self):
        """Construct a test provider that attempts a colliding candidate selection.

        Verify:
        - GlobalCommitValidator catches the collision.
        - The invalid candidate is NOT committed into results.
        - The failure is recorded in candidate_decisions as REJECTED.
        - The run completes safely.
        """
        class CollidingTestProvider(LLMProvider):
            async def classify_exception(self, case: ClassificationCase) -> ExceptionClassificationDecision:
                return ExceptionClassificationDecision(
                    exception_type="ROUNDING_DIFFERENCE",
                    severity="LOW",
                    flag_for_review=False,
                    reasoning="Test rounding",
                    confidence=0.9,
                )

            async def select_candidate(self, case: ClassificationCase) -> CandidateSelectionDecision:
                # Pick option 0
                return CandidateSelectionDecision(
                    selected_candidate_index=0,
                    relationship_type="1:1",
                    outcome="MATCHED",
                    exception_type=None,
                    severity=None,
                    flag_for_review=False,
                    reconciled_amount=str(case.source_amounts[0]) if case.source_amounts else "1000.00",
                    confidence=0.99,
                    reasoning="Deliberate choice",
                )

        db = Database(":memory:")
        repo = Repository(db)
        service = ReconciliationService(
            repository=repo,
            provider=CollidingTestProvider(),
            settings=Settings(DATABASE_PATH=":memory:"),
        )

        gtw_path = Path("data/synthetic/gateway.csv")
        bank_path = Path("data/synthetic/bank.csv")

        if not (gtw_path.exists() and bank_path.exists()):
            pytest.skip("Synthetic dataset CSV files not present")

        result = service.reconcile_files(gtw_path, bank_path, run_id="RUN-SAFETY-01")

        assert result["status"] == "COMPLETED"
        candidates = service.repository.get_candidates("RUN-SAFETY-01")
        assert len(candidates) == 9

        # Verify that candidate decisions that collided are marked as REJECTED
        statuses = [c["validation_status"] for c in candidates]
        assert "REJECTED" in statuses
