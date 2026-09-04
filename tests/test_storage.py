"""Unit tests for SQLite database persistence and repository layer."""

from datetime import date
from decimal import Decimal

import pytest

from eagle.models.canonical import CanonicalRecord
from eagle.models.enums import ExceptionType, ReconciliationOutcome, RelationshipType, Severity
from eagle.models.reconciliation import ReconciliationResult
from eagle.rules.models import OperatorCorrection, ReconciliationRule
from eagle.storage.database import Database, normalize_db_path
from eagle.storage.repository import Repository



@pytest.fixture
def repo():
    """In-memory SQLite repository for testing."""
    db = Database(":memory:")
    return Repository(db)


class TestDatabaseAndRepository:
    """Test suite for Database connection and Repository data access."""

    def test_database_initialization(self, repo):
        # Verify tables were created
        conn = repo.db.get_connection()
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {t["name"] for t in tables}
        assert "runs" in table_names
        assert "records" in table_names
        assert "reconciliation_results" in table_names
        assert "candidate_decisions" in table_names
        assert "audit_logs" in table_names

    def test_normalize_db_path(self):
        assert normalize_db_path("sqlite:///:memory:") == ":memory:"
        assert normalize_db_path("sqlite:///./test.db") == "./test.db"
        assert normalize_db_path("") == ":memory:"

    def test_create_and_get_run(self, repo):
        run = repo.create_run(
            run_id="RUN-001",
            status="PROCESSING",
            ai_provider="mock",
            total_records=10,
            source_count=5,
            target_count=5,
        )
        assert run is not None
        assert run["run_id"] == "RUN-001"
        assert run["status"] == "PROCESSING"
        assert run["ai_provider"] == "mock"
        assert run["total_records"] == 10

        fetched = repo.get_run("RUN-001")
        assert fetched["run_id"] == "RUN-001"

    def test_update_run_status_and_metrics(self, repo):
        repo.create_run(run_id="RUN-002", status="PROCESSING")
        updated = repo.update_run(
            run_id="RUN-002",
            status="COMPLETED",
            matched_count=8,
            exception_count=2,
            missing_count=1,
            unresolved_count=0,
            completed_at="2025-01-20T12:00:00Z",
        )
        assert updated["status"] == "COMPLETED"
        assert updated["matched_count"] == 8
        assert updated["exception_count"] == 2
        assert updated["missing_count"] == 1
        assert updated["completed_at"] == "2025-01-20T12:00:00Z"

    def test_list_runs(self, repo):
        repo.create_run(run_id="RUN-A")
        repo.create_run(run_id="RUN-B")
        runs = repo.list_runs()
        assert len(runs) >= 2
        run_ids = [r["run_id"] for r in runs]
        assert "RUN-A" in run_ids
        assert "RUN-B" in run_ids

    def test_save_and_get_records(self, repo):
        repo.create_run(run_id="RUN-REC")
        records = [
            CanonicalRecord(
                record_id="REC-01",
                transaction_id="TXN-01",
                source="GATEWAY",
                source_reference="REF-01",
                amount=Decimal("1000.50"),
                currency="INR",
                transaction_date=date(2025, 1, 15),
                settlement_date=date(2025, 1, 15),
                counterparty="Acme",
                status="COMPLETED",
                transaction_type="PAYMENT",
            ),
            CanonicalRecord(
                record_id="REC-02",
                transaction_id="TXN-02",
                source="BANK",
                source_reference="REF-01",
                amount=Decimal("1000.50"),
                currency="INR",
                transaction_date=date(2025, 1, 16),
                settlement_date=date(2025, 1, 16),
                counterparty="Acme",
                status="POSTED",
                transaction_type="CREDIT",
            ),
        ]
        repo.save_records("RUN-REC", records)

        retrieved = repo.get_records("RUN-REC")
        assert len(retrieved) == 2
        assert retrieved[0].record_id == "REC-01"
        assert retrieved[0].amount == Decimal("1000.50")
        assert retrieved[1].record_id == "REC-02"

        # Filter by source
        gtw_only = repo.get_records("RUN-REC", source="GATEWAY")
        assert len(gtw_only) == 1
        assert gtw_only[0].record_id == "REC-01"

    def test_save_and_get_results(self, repo):
        repo.create_run(run_id="RUN-RES")
        results = [
            ReconciliationResult(
                relationship_id="REL-01",
                relationship_type=RelationshipType.ONE_TO_ONE,
                source_record_ids=["GTW-01"],
                target_record_ids=["BANK-01"],
                outcome=ReconciliationOutcome.MATCHED,
                reconciled_amount=Decimal("500.00"),
            ),
            ReconciliationResult(
                relationship_id="REL-02",
                relationship_type=RelationshipType.ONE_TO_ONE,
                source_record_ids=["GTW-02"],
                target_record_ids=["BANK-02"],
                outcome=ReconciliationOutcome.EXCEPTION,
                exception_type=ExceptionType.SETTLEMENT_DELAY,
                severity=Severity.HIGH,
                flag_for_review=True,
                reconciled_amount=Decimal("750.00"),
            ),
        ]
        repo.save_results("RUN-RES", results, provenance="TEST")

        all_res = repo.get_results("RUN-RES")
        assert len(all_res) == 2

        matched_res = repo.get_results("RUN-RES", outcome="MATCHED")
        assert len(matched_res) == 1
        assert matched_res[0].relationship_id == "REL-01"

        exceptions = repo.get_exceptions("RUN-RES")
        assert len(exceptions) == 1
        assert exceptions[0].relationship_id == "REL-02"
        assert exceptions[0].exception_type == ExceptionType.SETTLEMENT_DELAY
        assert exceptions[0].severity == Severity.HIGH
        assert exceptions[0].flag_for_review is True

    def test_save_and_get_candidate_decisions(self, repo):
        repo.create_run(run_id="RUN-CAND")
        decisions = [
            {
                "anchor_record_id": "GTW-C01",
                "candidate_options": [
                    {"index": 0, "source_record_ids": ["GTW-C01"], "target_record_ids": ["BANK-C01-1"]},
                    {"index": 1, "source_record_ids": ["GTW-C01"], "target_record_ids": ["BANK-C01-2"]},
                ],
                "selected_candidate_index": 0,
                "ai_outcome": "MATCHED",
                "ai_exception_type": None,
                "confidence": 0.95,
                "reasoning": "Matching amount and reference",
                "validation_status": "COMMITTED",
                "rejection_reason": None,
            }
        ]
        repo.save_candidate_decisions("RUN-CAND", decisions)

        retrieved = repo.get_candidates("RUN-CAND")
        assert len(retrieved) == 1
        assert retrieved[0]["anchor_record_id"] == "GTW-C01"
        assert retrieved[0]["selected_candidate_index"] == 0
        assert retrieved[0]["validation_status"] == "COMMITTED"
        assert len(retrieved[0]["candidate_options"]) == 2

    def test_save_and_get_audit_logs(self, repo):
        repo.create_run(run_id="RUN-AUDIT")
        repo.save_audit_event("RUN-AUDIT", "RUN_CREATED", {"provider": "mock"})
        repo.save_audit_event("RUN-AUDIT", "RECONCILIATION_STARTED", {"sources": 10})
        repo.save_audit_event("RUN-AUDIT", "RUN_COMPLETED", {"matched": 8})

        logs = repo.get_audit_logs("RUN-AUDIT")
        assert len(logs) == 3
        assert logs[0]["event_type"] == "RUN_CREATED"
        assert logs[0]["details"]["provider"] == "mock"
        assert logs[1]["event_type"] == "RECONCILIATION_STARTED"
        assert logs[2]["event_type"] == "RUN_COMPLETED"

    def test_transaction_rollback_on_error(self, repo):
        repo.create_run(run_id="RUN-ROLLBACK")
        with pytest.raises(RuntimeError):
            with repo.db.transaction() as conn:
                conn.execute(
                    "INSERT INTO audit_logs (run_id, timestamp, event_type) VALUES (?, ?, ?)",
                    ("RUN-ROLLBACK", "2025-01-01", "WILL_FAIL"),
                )
                raise RuntimeError("Simulated failure")

        logs = repo.get_audit_logs("RUN-ROLLBACK")
        assert len(logs) == 0

    def test_run_isolation(self, repo):
        repo.create_run(run_id="RUN-1")
        repo.create_run(run_id="RUN-2")

        rec1 = [CanonicalRecord(
            record_id="R-1", transaction_id="T-1", source="GATEWAY", source_reference="REF",
            amount=Decimal("100"), currency="INR", transaction_date=date(2025, 1, 1),
            settlement_date=date(2025, 1, 1), counterparty="A", status="C", transaction_type="P"
        )]
        rec2 = [CanonicalRecord(
            record_id="R-2", transaction_id="T-2", source="BANK", source_reference="REF",
            amount=Decimal("100"), currency="INR", transaction_date=date(2025, 1, 1),
            settlement_date=date(2025, 1, 1), counterparty="A", status="C", transaction_type="P"
        )]

        repo.save_records("RUN-1", rec1)
        repo.save_records("RUN-2", rec2)

        assert len(repo.get_records("RUN-1")) == 1
        assert repo.get_records("RUN-1")[0].record_id == "R-1"

        assert len(repo.get_records("RUN-2")) == 1
        assert repo.get_records("RUN-2")[0].record_id == "R-2"

    def test_delete_run_success(self, repo):
        # Create Run A with full operational data
        repo.create_run(run_id="RUN-DEL-A", status="COMPLETED")
        repo.save_records("RUN-DEL-A", [
            CanonicalRecord(
                record_id="REC-A1", transaction_id="TXN-A1", source="GATEWAY", source_reference="REF-A",
                amount=Decimal("100"), currency="INR", transaction_date=date(2025, 1, 1),
                settlement_date=date(2025, 1, 1), counterparty="Alpha", status="C", transaction_type="P"
            )
        ])
        repo.save_results("RUN-DEL-A", [
            ReconciliationResult(
                relationship_id="REL-A1",
                relationship_type=RelationshipType.ONE_TO_ONE,
                source_record_ids=["REC-A1"],
                target_record_ids=[],
                outcome=ReconciliationOutcome.EXCEPTION,
                reconciled_amount=Decimal("100.00"),
            )
        ])
        repo.save_candidate_decisions("RUN-DEL-A", [
            {"anchor_record_id": "REC-A1", "candidate_options": [], "selected_candidate_index": None, "validation_status": "UNRESOLVED"}
        ])
        repo.save_audit_event("RUN-DEL-A", "RUN_COMPLETED", {"matched": 0})
        repo.save_correction(OperatorCorrection(
            correction_id="CORR-A1", run_id="RUN-DEL-A", relationship_id="REL-A1",
            original_outcome="EXCEPTION", original_exception_type=None,
            original_source_ids=["REC-A1"], original_target_ids=[],
            corrected_outcome="MATCHED", corrected_exception_type=None,
            corrected_source_ids=["REC-A1"], corrected_target_ids=["BANK-A1"],
            operator_reason="Manual fix", created_at="2025-01-01T00:00:00Z", generated_rule_id="RULE-A1"
        ))

        # Create Run B and Global Rule to verify non-deletion
        repo.create_run(run_id="RUN-DEL-B", status="COMPLETED")
        repo.save_records("RUN-DEL-B", [
            CanonicalRecord(
                record_id="REC-B1", transaction_id="TXN-B1", source="GATEWAY", source_reference="REF-B",
                amount=Decimal("200"), currency="INR", transaction_date=date(2025, 1, 1),
                settlement_date=date(2025, 1, 1), counterparty="Beta", status="C", transaction_type="P"
            )
        ])
        repo.save_rule(ReconciliationRule(
            rule_id="RULE-A1", name="Alpha Rule", description="Test",
            source_counterparty_pattern="Alpha",
            target_action="PREFER_CANDIDATE",
            resulting_outcome="MATCHED", confidence=1.0, is_active=True, created_at="2025-01-01T00:00:00Z",
            source_correction_id="CORR-A1"
        ))

        # Execute run deletion
        deleted = repo.delete_run("RUN-DEL-A")
        assert deleted is True

        # Verify Run A data is completely removed
        assert repo.get_run("RUN-DEL-A") is None
        assert len(repo.get_records("RUN-DEL-A")) == 0
        assert len(repo.get_results("RUN-DEL-A")) == 0
        assert len(repo.get_candidates("RUN-DEL-A")) == 0
        assert len(repo.get_audit_logs("RUN-DEL-A")) == 0
        assert len(repo.get_corrections("RUN-DEL-A")) == 0

        # Verify Run B data is completely intact
        assert repo.get_run("RUN-DEL-B") is not None
        assert len(repo.get_records("RUN-DEL-B")) == 1

        # Verify Global Rule is completely intact
        assert repo.get_rule("RULE-A1") is not None

    def test_delete_run_not_found(self, repo):
        assert repo.delete_run("NON_EXISTENT_RUN") is False

    def test_delete_rule_success(self, repo):
        repo.create_run(run_id="RUN-ORIG", status="COMPLETED")
        repo.save_correction(OperatorCorrection(
            correction_id="CORR-ORIG", run_id="RUN-ORIG", relationship_id="REL-ORIG",
            original_outcome="EXCEPTION", original_exception_type=None,
            original_source_ids=["REC-1"], original_target_ids=[],
            corrected_outcome="MATCHED", corrected_exception_type=None,
            corrected_source_ids=["REC-1"], corrected_target_ids=["BANK-1"],
            operator_reason="Manual fix", created_at="2025-01-01T00:00:00Z", generated_rule_id="RULE-TO-DEL"
        ))
        repo.save_rule(ReconciliationRule(
            rule_id="RULE-TO-DEL", name="Rule to delete", description="Test",
            source_counterparty_pattern="TestCP",
            target_action="PREFER_CANDIDATE",
            resulting_outcome="MATCHED", confidence=1.0, is_active=True, created_at="2025-01-01T00:00:00Z",
            source_correction_id="CORR-ORIG"
        ))


        # Delete rule
        deleted = repo.delete_rule("RULE-TO-DEL")
        assert deleted is True

        # Rule should be gone
        assert repo.get_rule("RULE-TO-DEL") is None

        # Originating run and correction must remain intact
        assert repo.get_run("RUN-ORIG") is not None
        assert repo.get_correction("CORR-ORIG") is not None
        assert repo.get_correction("CORR-ORIG").generated_rule_id == "RULE-TO-DEL"

    def test_delete_rule_not_found(self, repo):
        assert repo.delete_rule("NON_EXISTENT_RULE") is False

    def test_rerun_deletion_isolation(self, repo):
        repo.create_run(run_id="RUN-PARENT", status="COMPLETED")
        repo.create_run(run_id="RUN-PARENT-RERUN-001", status="COMPLETED")

        # Deleting rerun does not delete parent
        assert repo.delete_run("RUN-PARENT-RERUN-001") is True
        assert repo.get_run("RUN-PARENT-RERUN-001") is None
        assert repo.get_run("RUN-PARENT") is not None

        # Recreate rerun and delete parent -> rerun remains intact
        repo.create_run(run_id="RUN-PARENT-RERUN-002", status="COMPLETED")
        assert repo.delete_run("RUN-PARENT") is True
        assert repo.get_run("RUN-PARENT") is None
        assert repo.get_run("RUN-PARENT-RERUN-002") is not None

