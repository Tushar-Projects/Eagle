"""Tests for Eagle domain models and ground-truth data contract."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from eagle.models.enums import (
    ExceptionType,
    ReconciliationOutcome,
    RelationshipType,
    Severity,
)
from eagle.models.canonical import CanonicalRecord
from eagle.models.reconciliation import ReconciliationResult
from eagle.models.ground_truth import GroundTruthDataset, GroundTruthRelationship


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_record(**overrides) -> dict:
    """Return minimal valid canonical record fields, with optional overrides."""
    base = {
        "record_id": "rec_001",
        "transaction_id": "txn_001",
        "source": "razorpay",
        "source_reference": "pay_ABC123",
        "amount": Decimal("1000.00"),
        "currency": "INR",
        "transaction_date": date(2025, 1, 15),
        "settlement_date": date(2025, 1, 17),
        "counterparty": "merchant_xyz",
        "status": "captured",
        "transaction_type": "payment",
    }
    base.update(overrides)
    return base


def _minimal_result(**overrides) -> dict:
    """Return minimal valid reconciliation result fields."""
    base = {
        "relationship_id": "rel_001",
        "relationship_type": RelationshipType.ONE_TO_ONE,
        "source_record_ids": ["rec_001"],
        "target_record_ids": ["rec_002"],
        "outcome": ReconciliationOutcome.MATCHED,
    }
    base.update(overrides)
    return base


def _minimal_gt_relationship(**overrides) -> dict:
    """Return minimal valid ground-truth relationship fields."""
    base = {
        "relationship_id": "gt_001",
        "relationship_type": RelationshipType.ONE_TO_ONE,
        "source_record_ids": ["rec_001"],
        "target_record_ids": ["rec_002"],
        "expected_outcome": ReconciliationOutcome.MATCHED,
        "expected_reconciled_amount": Decimal("1000.00"),
    }
    base.update(overrides)
    return base


# ===========================================================================
# 1. Canonical Record — valid construction
# ===========================================================================

class TestCanonicalRecordValid:

    def test_minimal_record(self):
        rec = CanonicalRecord(**_minimal_record())
        assert rec.record_id == "rec_001"
        assert rec.amount == Decimal("1000.00")
        assert rec.transaction_date == date(2025, 1, 15)
        assert rec.settlement_date == date(2025, 1, 17)

    def test_nullable_optional_fields_default_none(self):
        rec = CanonicalRecord(**_minimal_record())
        assert rec.gross_amount is None
        assert rec.fee_amount is None
        assert rec.net_amount is None

    def test_nullable_optional_fields_set(self):
        rec = CanonicalRecord(**_minimal_record(
            gross_amount=Decimal("1050.00"),
            fee_amount=Decimal("50.00"),
            net_amount=Decimal("1000.00"),
        ))
        assert rec.gross_amount == Decimal("1050.00")
        assert rec.fee_amount == Decimal("50.00")
        assert rec.net_amount == Decimal("1000.00")

    def test_related_record_ids_defaults_empty(self):
        rec = CanonicalRecord(**_minimal_record())
        assert rec.related_record_ids == []

    def test_related_record_ids_set(self):
        rec = CanonicalRecord(**_minimal_record(
            related_record_ids=["rec_002", "rec_003"],
        ))
        assert rec.related_record_ids == ["rec_002", "rec_003"]

    def test_provenance_preserved(self):
        rec = CanonicalRecord(**_minimal_record(
            source="bank_statement",
            source_reference="stmt_ref_456",
        ))
        assert rec.source == "bank_statement"
        assert rec.source_reference == "stmt_ref_456"


# ===========================================================================
# 2. Extraction Confidence — field-level
# ===========================================================================

class TestExtractionConfidence:

    def test_confidence_defaults_empty(self):
        rec = CanonicalRecord(**_minimal_record())
        assert rec.extraction_confidence == {}

    def test_field_level_confidence(self):
        rec = CanonicalRecord(**_minimal_record(
            extraction_confidence={
                "amount": 0.95,
                "currency": 0.99,
                "transaction_date": 0.87,
            }
        ))
        assert rec.extraction_confidence["amount"] == 0.95
        assert rec.extraction_confidence["currency"] == 0.99
        assert rec.extraction_confidence["transaction_date"] == 0.87

    def test_confidence_boundary_zero(self):
        rec = CanonicalRecord(**_minimal_record(
            extraction_confidence={"amount": 0.0}
        ))
        assert rec.extraction_confidence["amount"] == 0.0

    def test_confidence_boundary_one(self):
        rec = CanonicalRecord(**_minimal_record(
            extraction_confidence={"amount": 1.0}
        ))
        assert rec.extraction_confidence["amount"] == 1.0

    def test_confidence_above_one_rejected(self):
        with pytest.raises(ValidationError, match="between 0.0 and 1.0"):
            CanonicalRecord(**_minimal_record(
                extraction_confidence={"amount": 1.5}
            ))

    def test_confidence_below_zero_rejected(self):
        with pytest.raises(ValidationError, match="between 0.0 and 1.0"):
            CanonicalRecord(**_minimal_record(
                extraction_confidence={"amount": -0.1}
            ))

    def test_confidence_nonexistent_field_rejected(self):
        """Keys must correspond to actual canonical field names."""
        with pytest.raises(ValidationError, match="not a valid canonical field"):
            CanonicalRecord(**_minimal_record(
                extraction_confidence={"nonexistent_field": 0.9}
            ))

    def test_confidence_on_nullable_fields_accepted(self):
        """Nullable fields (gross_amount, fee_amount, net_amount) are valid keys."""
        rec = CanonicalRecord(**_minimal_record(
            gross_amount=Decimal("1050.00"),
            fee_amount=Decimal("50.00"),
            net_amount=Decimal("1000.00"),
            extraction_confidence={
                "gross_amount": 0.85,
                "fee_amount": 0.90,
                "net_amount": 0.88,
            }
        ))
        assert rec.extraction_confidence["gross_amount"] == 0.85

    def test_confidence_all_required_fields_accepted(self):
        """Every required canonical field name is a valid confidence key."""
        required_fields = [
            "record_id", "transaction_id", "source", "source_reference",
            "amount", "currency", "transaction_date", "settlement_date",
            "counterparty", "status", "transaction_type", "related_record_ids",
        ]
        confidence = {f: 0.95 for f in required_fields}
        rec = CanonicalRecord(**_minimal_record(
            extraction_confidence=confidence
        ))
        assert len(rec.extraction_confidence) == len(required_fields)


# ===========================================================================
# 3. Enums — RelationshipType
# ===========================================================================

class TestRelationshipType:

    def test_valid_values(self):
        assert RelationshipType.ONE_TO_ONE.value == "1:1"
        assert RelationshipType.ONE_TO_MANY.value == "1:N"
        assert RelationshipType.MANY_TO_ONE.value == "N:1"

    def test_all_values_exhaustive(self):
        assert len(RelationshipType) == 3

    def test_invalid_relationship_type_rejected(self):
        with pytest.raises(ValidationError):
            ReconciliationResult(**_minimal_result(
                relationship_type="N:M"
            ))

    def test_construction_from_string(self):
        result = ReconciliationResult(**_minimal_result(
            relationship_type="1:N"
        ))
        assert result.relationship_type == RelationshipType.ONE_TO_MANY


# ===========================================================================
# 4. Enums — ReconciliationOutcome
# ===========================================================================

class TestReconciliationOutcome:

    def test_valid_values(self):
        assert ReconciliationOutcome.MATCHED.value == "MATCHED"
        assert ReconciliationOutcome.EXCEPTION.value == "EXCEPTION"

    def test_all_values_exhaustive(self):
        assert len(ReconciliationOutcome) == 2

    def test_invalid_outcome_rejected(self):
        with pytest.raises(ValidationError):
            ReconciliationResult(**_minimal_result(
                outcome="PARTIAL"
            ))


# ===========================================================================
# 5. Enums — ExceptionType (closed AI taxonomy)
# ===========================================================================

class TestExceptionType:

    def test_all_ten_values(self):
        expected = {
            "SETTLEMENT_DELAY",
            "FEE_DEDUCTION",
            "ROUNDING_DIFFERENCE",
            "PARTIAL_SETTLEMENT",
            "SPLIT_SETTLEMENT",
            "DUPLICATE",
            "MISSING_RECORD",
            "CURRENCY_MISMATCH",
            "POSSIBLE_DUPLICATE",
            "UNKNOWN",
        }
        assert {e.value for e in ExceptionType} == expected
        assert len(ExceptionType) == 10

    def test_invalid_exception_type_rejected(self):
        with pytest.raises(ValidationError):
            ReconciliationResult(**_minimal_result(
                exception_type="VALIDATION_EXCEPTION"
            ))

    def test_duplicate_vs_possible_duplicate_distinct(self):
        assert ExceptionType.DUPLICATE != ExceptionType.POSSIBLE_DUPLICATE
        assert ExceptionType.DUPLICATE.value == "DUPLICATE"
        assert ExceptionType.POSSIBLE_DUPLICATE.value == "POSSIBLE_DUPLICATE"


# ===========================================================================
# 6. Enums — Severity
# ===========================================================================

class TestSeverity:

    def test_valid_values(self):
        assert Severity.LOW.value == "LOW"
        assert Severity.MEDIUM.value == "MEDIUM"
        assert Severity.HIGH.value == "HIGH"

    def test_all_values_exhaustive(self):
        assert len(Severity) == 3

    def test_invalid_severity_rejected(self):
        with pytest.raises(ValidationError):
            ReconciliationResult(**_minimal_result(
                severity="CRITICAL"
            ))


# ===========================================================================
# 7. ReconciliationResult — outcome + classification combinations
# ===========================================================================

class TestReconciliationResultCombinations:

    def test_matched_no_classification(self):
        result = ReconciliationResult(**_minimal_result(
            outcome=ReconciliationOutcome.MATCHED,
        ))
        assert result.outcome == ReconciliationOutcome.MATCHED
        assert result.exception_type is None

    def test_matched_rounding_difference(self):
        result = ReconciliationResult(**_minimal_result(
            outcome=ReconciliationOutcome.MATCHED,
            exception_type=ExceptionType.ROUNDING_DIFFERENCE,
            severity=Severity.LOW,
        ))
        assert result.outcome == ReconciliationOutcome.MATCHED
        assert result.exception_type == ExceptionType.ROUNDING_DIFFERENCE

    def test_matched_fee_deduction(self):
        result = ReconciliationResult(**_minimal_result(
            outcome=ReconciliationOutcome.MATCHED,
            exception_type=ExceptionType.FEE_DEDUCTION,
            severity=Severity.MEDIUM,
        ))
        assert result.outcome == ReconciliationOutcome.MATCHED
        assert result.exception_type == ExceptionType.FEE_DEDUCTION

    def test_matched_settlement_delay(self):
        result = ReconciliationResult(**_minimal_result(
            outcome=ReconciliationOutcome.MATCHED,
            exception_type=ExceptionType.SETTLEMENT_DELAY,
            severity=Severity.HIGH,
            flag_for_review=True,
        ))
        assert result.outcome == ReconciliationOutcome.MATCHED
        assert result.exception_type == ExceptionType.SETTLEMENT_DELAY
        assert result.severity == Severity.HIGH
        assert result.flag_for_review is True

    def test_exception_missing_record(self):
        result = ReconciliationResult(**_minimal_result(
            outcome=ReconciliationOutcome.EXCEPTION,
            exception_type=ExceptionType.MISSING_RECORD,
            severity=Severity.HIGH,
            flag_for_review=True,
        ))
        assert result.outcome == ReconciliationOutcome.EXCEPTION
        assert result.exception_type == ExceptionType.MISSING_RECORD

    def test_exception_currency_mismatch(self):
        result = ReconciliationResult(**_minimal_result(
            outcome=ReconciliationOutcome.EXCEPTION,
            exception_type=ExceptionType.CURRENCY_MISMATCH,
            severity=Severity.HIGH,
        ))
        assert result.outcome == ReconciliationOutcome.EXCEPTION
        assert result.exception_type == ExceptionType.CURRENCY_MISMATCH

    def test_flag_for_review_defaults_false(self):
        result = ReconciliationResult(**_minimal_result())
        assert result.flag_for_review is False

    def test_severity_on_non_settlement_delay(self):
        """severity is not restricted to settlement-delay cases."""
        result = ReconciliationResult(**_minimal_result(
            exception_type=ExceptionType.DUPLICATE,
            severity=Severity.MEDIUM,
            flag_for_review=True,
        ))
        assert result.severity == Severity.MEDIUM
        assert result.flag_for_review is True


# ===========================================================================
# 8. ReconciliationResult — relationship types with outcomes
# ===========================================================================

class TestRelationshipTypeOutcomes:

    def test_one_to_one_matched(self):
        result = ReconciliationResult(**_minimal_result(
            relationship_type=RelationshipType.ONE_TO_ONE,
            outcome=ReconciliationOutcome.MATCHED,
        ))
        assert result.relationship_type == RelationshipType.ONE_TO_ONE

    def test_one_to_many_matched(self):
        result = ReconciliationResult(**_minimal_result(
            relationship_type=RelationshipType.ONE_TO_MANY,
            source_record_ids=["rec_001"],
            target_record_ids=["rec_002", "rec_003"],
            outcome=ReconciliationOutcome.MATCHED,
        ))
        assert result.relationship_type == RelationshipType.ONE_TO_MANY

    def test_many_to_one_matched(self):
        result = ReconciliationResult(**_minimal_result(
            relationship_type=RelationshipType.MANY_TO_ONE,
            source_record_ids=["rec_001", "rec_002"],
            target_record_ids=["rec_003"],
            outcome=ReconciliationOutcome.MATCHED,
        ))
        assert result.relationship_type == RelationshipType.MANY_TO_ONE

    def test_one_to_one_exception(self):
        result = ReconciliationResult(**_minimal_result(
            relationship_type=RelationshipType.ONE_TO_ONE,
            outcome=ReconciliationOutcome.EXCEPTION,
            exception_type=ExceptionType.MISSING_RECORD,
        ))
        assert result.relationship_type == RelationshipType.ONE_TO_ONE
        assert result.outcome == ReconciliationOutcome.EXCEPTION


# ===========================================================================
# 9. Ground-truth relationship
# ===========================================================================

class TestGroundTruthRelationship:

    def test_valid_relationship(self):
        gt = GroundTruthRelationship(**_minimal_gt_relationship())
        assert gt.relationship_id == "gt_001"
        assert gt.relationship_type == RelationshipType.ONE_TO_ONE
        assert gt.expected_outcome == ReconciliationOutcome.MATCHED
        assert gt.expected_reconciled_amount == Decimal("1000.00")

    def test_nullable_expected_exception_type(self):
        gt = GroundTruthRelationship(**_minimal_gt_relationship())
        assert gt.expected_exception_type is None

    def test_expected_exception_type_set(self):
        gt = GroundTruthRelationship(**_minimal_gt_relationship(
            expected_outcome=ReconciliationOutcome.EXCEPTION,
            expected_exception_type=ExceptionType.MISSING_RECORD,
        ))
        assert gt.expected_exception_type == ExceptionType.MISSING_RECORD

    def test_notes_accepted(self):
        gt = GroundTruthRelationship(**_minimal_gt_relationship(
            notes="This is a known rounding case from Jan batch",
        ))
        assert gt.notes == "This is a known rounding case from Jan batch"

    def test_notes_default_empty(self):
        gt = GroundTruthRelationship(**_minimal_gt_relationship())
        assert gt.notes == ""

    def test_invalid_relationship_type_rejected(self):
        with pytest.raises(ValidationError):
            GroundTruthRelationship(**_minimal_gt_relationship(
                relationship_type="N:M"
            ))

    def test_invalid_outcome_rejected(self):
        with pytest.raises(ValidationError):
            GroundTruthRelationship(**_minimal_gt_relationship(
                expected_outcome="PARTIAL"
            ))

    def test_invalid_exception_type_rejected(self):
        with pytest.raises(ValidationError):
            GroundTruthRelationship(**_minimal_gt_relationship(
                expected_exception_type="VALIDATION_EXCEPTION"
            ))

    def test_one_to_many_matched(self):
        """A 1:N relationship can have expected_outcome=MATCHED."""
        gt = GroundTruthRelationship(**_minimal_gt_relationship(
            relationship_type=RelationshipType.ONE_TO_MANY,
            source_record_ids=["rec_001"],
            target_record_ids=["rec_002", "rec_003"],
            expected_outcome=ReconciliationOutcome.MATCHED,
        ))
        assert gt.relationship_type == RelationshipType.ONE_TO_MANY
        assert gt.expected_outcome == ReconciliationOutcome.MATCHED

    def test_many_to_one_matched(self):
        """An N:1 relationship can have expected_outcome=MATCHED."""
        gt = GroundTruthRelationship(**_minimal_gt_relationship(
            relationship_type=RelationshipType.MANY_TO_ONE,
            source_record_ids=["rec_001", "rec_002"],
            target_record_ids=["rec_003"],
            expected_outcome=ReconciliationOutcome.MATCHED,
        ))
        assert gt.relationship_type == RelationshipType.MANY_TO_ONE
        assert gt.expected_outcome == ReconciliationOutcome.MATCHED


# ===========================================================================
# 9b. MISSING_RECORD symmetric representation
# ===========================================================================

class TestMissingRecordRepresentation:
    """Verify symmetric MISSING_RECORD convention.

    An empty list on source_record_ids or target_record_ids represents
    the absent side.  No nulls, sentinels, or placeholder IDs are used.
    """

    # --- Ground-truth: source exists, target missing ---

    def test_gt_source_exists_target_missing(self):
        gt = GroundTruthRelationship(**_minimal_gt_relationship(
            relationship_type=RelationshipType.ONE_TO_ONE,
            source_record_ids=["GTW-042"],
            target_record_ids=[],
            expected_outcome=ReconciliationOutcome.EXCEPTION,
            expected_exception_type=ExceptionType.MISSING_RECORD,
        ))
        assert gt.source_record_ids == ["GTW-042"]
        assert gt.target_record_ids == []
        assert isinstance(gt.target_record_ids, list)
        assert gt.relationship_type == RelationshipType.ONE_TO_ONE
        assert gt.expected_outcome == ReconciliationOutcome.EXCEPTION
        assert gt.expected_exception_type == ExceptionType.MISSING_RECORD

    # --- Ground-truth: target exists, source missing ---

    def test_gt_target_exists_source_missing(self):
        gt = GroundTruthRelationship(**_minimal_gt_relationship(
            relationship_type=RelationshipType.ONE_TO_ONE,
            source_record_ids=[],
            target_record_ids=["BANK-042"],
            expected_outcome=ReconciliationOutcome.EXCEPTION,
            expected_exception_type=ExceptionType.MISSING_RECORD,
        ))
        assert gt.source_record_ids == []
        assert isinstance(gt.source_record_ids, list)
        assert gt.target_record_ids == ["BANK-042"]
        assert gt.relationship_type == RelationshipType.ONE_TO_ONE
        assert gt.expected_outcome == ReconciliationOutcome.EXCEPTION
        assert gt.expected_exception_type == ExceptionType.MISSING_RECORD

    # --- ReconciliationResult: source exists, target missing ---

    def test_result_source_exists_target_missing(self):
        result = ReconciliationResult(**_minimal_result(
            relationship_type=RelationshipType.ONE_TO_ONE,
            source_record_ids=["GTW-042"],
            target_record_ids=[],
            outcome=ReconciliationOutcome.EXCEPTION,
            exception_type=ExceptionType.MISSING_RECORD,
        ))
        assert result.source_record_ids == ["GTW-042"]
        assert result.target_record_ids == []
        assert isinstance(result.target_record_ids, list)
        assert result.relationship_type == RelationshipType.ONE_TO_ONE

    # --- ReconciliationResult: target exists, source missing ---

    def test_result_target_exists_source_missing(self):
        result = ReconciliationResult(**_minimal_result(
            relationship_type=RelationshipType.ONE_TO_ONE,
            source_record_ids=[],
            target_record_ids=["BANK-042"],
            outcome=ReconciliationOutcome.EXCEPTION,
            exception_type=ExceptionType.MISSING_RECORD,
        ))
        assert result.source_record_ids == []
        assert isinstance(result.source_record_ids, list)
        assert result.target_record_ids == ["BANK-042"]
        assert result.relationship_type == RelationshipType.ONE_TO_ONE


# ===========================================================================
# 10. Ground-truth dataset
# ===========================================================================

class TestGroundTruthDataset:

    def test_valid_dataset(self):
        ds = GroundTruthDataset(relationships=[
            GroundTruthRelationship(**_minimal_gt_relationship()),
            GroundTruthRelationship(**_minimal_gt_relationship(
                relationship_id="gt_002",
                expected_outcome=ReconciliationOutcome.EXCEPTION,
                expected_exception_type=ExceptionType.CURRENCY_MISMATCH,
            )),
        ])
        assert len(ds.relationships) == 2

    def test_empty_dataset(self):
        ds = GroundTruthDataset(relationships=[])
        assert len(ds.relationships) == 0


# ===========================================================================
# 11. Date fields
# ===========================================================================

class TestDateFields:

    def test_date_objects(self):
        rec = CanonicalRecord(**_minimal_record())
        assert isinstance(rec.transaction_date, date)
        assert isinstance(rec.settlement_date, date)

    def test_dates_parsed_from_strings(self):
        rec = CanonicalRecord(**_minimal_record(
            transaction_date="2025-03-10",
            settlement_date="2025-03-12",
        ))
        assert rec.transaction_date == date(2025, 3, 10)
        assert rec.settlement_date == date(2025, 3, 12)

    def test_invalid_date_rejected(self):
        with pytest.raises(ValidationError):
            CanonicalRecord(**_minimal_record(
                transaction_date="not-a-date",
            ))

    def test_transaction_and_settlement_date_independent(self):
        """Both dates are independently represented."""
        rec = CanonicalRecord(**_minimal_record(
            transaction_date=date(2025, 6, 1),
            settlement_date=date(2025, 6, 4),
        ))
        assert rec.transaction_date != rec.settlement_date
        assert rec.transaction_date == date(2025, 6, 1)
        assert rec.settlement_date == date(2025, 6, 4)


# ===========================================================================
# 12. Monetary values — exact decimal semantics
# ===========================================================================

class TestMonetaryValues:

    def test_decimal_precision_preserved(self):
        rec = CanonicalRecord(**_minimal_record(
            amount=Decimal("999.99"),
        ))
        assert rec.amount == Decimal("999.99")

    def test_no_floating_point_drift(self):
        """Decimal arithmetic must not suffer float rounding."""
        a = Decimal("0.1") + Decimal("0.2")
        rec = CanonicalRecord(**_minimal_record(amount=a))
        assert rec.amount == Decimal("0.3")

    def test_fee_amounts_decimal(self):
        rec = CanonicalRecord(**_minimal_record(
            gross_amount=Decimal("1050.50"),
            fee_amount=Decimal("50.50"),
            net_amount=Decimal("1000.00"),
        ))
        assert rec.gross_amount - rec.fee_amount == rec.net_amount

    def test_reconciled_amount_decimal(self):
        result = ReconciliationResult(**_minimal_result(
            reconciled_amount=Decimal("12345.67"),
        ))
        assert result.reconciled_amount == Decimal("12345.67")

    def test_ground_truth_amount_decimal(self):
        gt = GroundTruthRelationship(**_minimal_gt_relationship(
            expected_reconciled_amount=Decimal("5000.25"),
        ))
        assert gt.expected_reconciled_amount == Decimal("5000.25")

    def test_invalid_amount_rejected(self):
        with pytest.raises(ValidationError):
            CanonicalRecord(**_minimal_record(
                amount="not_a_number",
            ))


# ===========================================================================
# 13. Package-level imports
# ===========================================================================

class TestPackageImports:

    def test_import_from_models_package(self):
        """All models importable from eagle.models."""
        from eagle.models import (
            CanonicalRecord,
            ExceptionType,
            GroundTruthDataset,
            GroundTruthRelationship,
            ReconciliationOutcome,
            ReconciliationResult,
            RelationshipType,
            Severity,
        )
        # Verify they are the correct types
        assert issubclass(RelationshipType, str)
        assert issubclass(ReconciliationOutcome, str)
        assert issubclass(ExceptionType, str)
        assert issubclass(Severity, str)
