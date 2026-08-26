"""Tests for the deterministic reconciliation engine."""
import csv
from datetime import datetime
from decimal import Decimal

from eagle.models.canonical import CanonicalRecord
from eagle.models.enums import ExceptionType, ReconciliationOutcome, RelationshipType, Severity
from eagle.reconciliation.engine import reconcile

GATEWAY_CSV = "data/synthetic/gateway.csv"
BANK_CSV = "data/synthetic/bank.csv"

def load_gateway_records() -> list[CanonicalRecord]:
    records = []
    with open(GATEWAY_CSV, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append(
                CanonicalRecord(
                    record_id=row["payment_id"],
                    transaction_id=row["payment_id"],
                    source="GATEWAY",
                    source_reference=row["merchant_txn_ref"],
                    amount=Decimal(row["amount"]),
                    currency=row["currency"],
                    transaction_date=datetime.strptime(row["created_at"], "%Y-%m-%d").date(),
                    # Assuming settlement date is not reliably known from gateway, 
                    # but model requires it. We map transaction_date to it for now if needed.
                    # Or map from created_at
                    settlement_date=datetime.strptime(row["created_at"], "%Y-%m-%d").date(),
                    counterparty=row.get("merchant_name", ""),
                    status="COMPLETED",
                    transaction_type="PAYMENT",
                    gross_amount=Decimal(row["gross_amount"]) if row.get("gross_amount") else None,
                    fee_amount=Decimal(row["fee"]) if row.get("fee") else None,
                    net_amount=Decimal(row["net_amount"]) if row.get("net_amount") else None,
                )
            )
    return records

def load_bank_records() -> list[CanonicalRecord]:
    records = []
    with open(BANK_CSV, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append(
                CanonicalRecord(
                    record_id=row["bank_reference"],
                    transaction_id=row["bank_reference"], # Using ref as txn ID
                    source="BANK",
                    source_reference=row["narration"],
                    amount=Decimal(row["settlement_amount"]),
                    currency=row["currency"],
                    # Often bank only has posting date, we assume it's settlement
                    transaction_date=datetime.strptime(row["posting_date"], "%Y-%m-%d").date(),
                    settlement_date=datetime.strptime(row["posting_date"], "%Y-%m-%d").date(),
                    counterparty=row.get("counterparty", ""),
                    status="POSTED",
                    transaction_type="CREDIT",
                    fee_amount=Decimal(row["fee"]) if row.get("fee") else None,
                )
            )
    return records

def test_engine_deterministic_resolution():
    sources = load_gateway_records()
    targets = load_bank_records()
    
    engine_output = reconcile(sources, targets)
    results = engine_output.results
    candidates = engine_output.candidates
    
    # Create lookups to verify outputs
    # For many cases, one gateway maps to one bank.
    source_map = {r.source_record_ids[0]: r for r in results if r.source_record_ids}
    
    # 1. Exact Reference Match (A-01)
    a01 = source_map["GTW-A01"]
    assert a01.outcome == ReconciliationOutcome.MATCHED
    assert a01.target_record_ids == ["BANK-A01"]
    assert a01.exception_type is None
    
    # 2. Normalized Reference Match (A-04)
    a04 = source_map["GTW-A04"]
    assert a04.outcome == ReconciliationOutcome.MATCHED
    assert a04.target_record_ids == ["BANK-A04"]
    
    # 3. Financial Match with Counterparty (A-05)
    a05 = source_map["GTW-A05"]
    assert a05.outcome == ReconciliationOutcome.MATCHED
    assert a05.target_record_ids == ["BANK-A05"]

    # 4. Rounding Difference (B-01)
    b01 = source_map["GTW-B01"]
    assert b01.outcome == ReconciliationOutcome.MATCHED
    assert b01.exception_type == ExceptionType.ROUNDING_DIFFERENCE
    
    # 5. Fee Deduction (B-04)
    b04 = source_map["GTW-B04"]
    assert b04.outcome == ReconciliationOutcome.MATCHED
    assert b04.exception_type == ExceptionType.FEE_DEDUCTION
    
    # 6. Settlement Delay (B-07 Medium Delay, B-08 High Delay)
    b07 = source_map["GTW-B07"]
    assert b07.outcome == ReconciliationOutcome.MATCHED
    assert b07.exception_type == ExceptionType.SETTLEMENT_DELAY
    assert b07.severity == Severity.MEDIUM
    
    b08 = source_map["GTW-B08"]
    assert b08.outcome == ReconciliationOutcome.MATCHED
    assert b08.exception_type == ExceptionType.SETTLEMENT_DELAY
    assert b08.severity == Severity.HIGH
    assert b08.flag_for_review is True
    
    # 7. MISSING_RECORD (D-01 Gateway Orphan, D-03 Bank Orphan)
    d01 = source_map["GTW-D01"]
    assert d01.outcome == ReconciliationOutcome.EXCEPTION
    assert d01.exception_type == ExceptionType.MISSING_RECORD
    assert d01.target_record_ids == []
    
    # Find bank orphan D-03 (BANK-ORPH-001)
    d03 = next(r for r in results if not r.source_record_ids and "BANK-ORPH-001" in r.target_record_ids)
    assert d03.outcome == ReconciliationOutcome.EXCEPTION
    assert d03.exception_type == ExceptionType.MISSING_RECORD
    
    # 8. Deterministic Duplicate (D-07)
    d07 = source_map["GTW-D07"]
    assert d07.outcome == ReconciliationOutcome.EXCEPTION
    assert d07.exception_type == ExceptionType.DUPLICATE
    assert d07.target_record_ids == []

    # 9. 1:N Aggregation Match (C-01)
    c01 = source_map["GTW-C01"]
    assert c01.outcome == ReconciliationOutcome.MATCHED
    assert c01.relationship_type == RelationshipType.ONE_TO_MANY
    assert set(c01.target_record_ids) == {"BANK-C01-1", "BANK-C01-2"}
    
    # 10. N:1 Aggregation Match (C-03)
    c03_1 = source_map["GTW-C03-1"]
    assert c03_1.outcome == ReconciliationOutcome.MATCHED
    assert c03_1.relationship_type == RelationshipType.MANY_TO_ONE
    assert c03_1.target_record_ids == ["BANK-C03"]
    assert set(c03_1.source_record_ids) == {"GTW-C03-1", "GTW-C03-2"}
    
    # 11. Unresolved semantics (E-06 Split Shortfall, D-06 Partial, D-05 Currency)
    e06 = source_map["GTW-E06"]
    assert e06.outcome == ReconciliationOutcome.EXCEPTION
    assert e06.exception_type is None
    assert e06.relationship_type == RelationshipType.ONE_TO_MANY
    assert set(e06.target_record_ids) == {"BANK-E06-1", "BANK-E06-2"}
    
    # D-06 and D-05 should be matched by exact reference but left UNRESOLVED for AI
    d06 = source_map["GTW-D06"]
    assert d06.outcome == ReconciliationOutcome.EXCEPTION
    assert d06.exception_type is None
    assert d06.target_record_ids == ["BANK-D06"]
    
    d05 = source_map["GTW-D05"]
    assert d05.outcome == ReconciliationOutcome.EXCEPTION
    assert d05.exception_type is None
    assert d05.target_record_ids == ["BANK-D05"]

    # 12. E-03 Ambiguity (should be unresolved candidate pool)
    # It must NOT be in results!
    assert "GTW-E03" not in source_map, "E-03 should not be a committed result"
    
    # It must be in candidates
    e03_candidates = [c for c in candidates if c.source_record_ids == ["GTW-E03"]]
    assert len(e03_candidates) == 1
    e03_evidence = e03_candidates[0]
    assert set(e03_evidence.candidate_target_record_ids) == {"BANK-E03", "BANK-D03"}
    # Must not be represented as 1:1 or 1:N in the relationship type field (it doesn't have one)
    assert not hasattr(e03_evidence, "relationship_type")
    
    # Generate diagnostic summary
    matches_1_to_1 = sum(1 for r in results if r.outcome == ReconciliationOutcome.MATCHED and r.relationship_type == RelationshipType.ONE_TO_ONE)
    matches_1_to_n = sum(1 for r in results if r.outcome == ReconciliationOutcome.MATCHED and r.relationship_type == RelationshipType.ONE_TO_MANY)
    matches_n_to_1 = sum(1 for r in results if r.outcome == ReconciliationOutcome.MATCHED and r.relationship_type == RelationshipType.MANY_TO_ONE)
    unresolved_cases = sum(1 for r in results if r.outcome == ReconciliationOutcome.EXCEPTION and r.exception_type is None)
    genuine_orphans = sum(1 for r in results if r.outcome == ReconciliationOutcome.EXCEPTION and r.exception_type == ExceptionType.MISSING_RECORD)
    duplicates = sum(1 for r in results if r.outcome == ReconciliationOutcome.EXCEPTION and r.exception_type == ExceptionType.DUPLICATE)
    candidate_pools = len(candidates)
    
    print("\n--- DETERMINISTIC BENCHMARK SUMMARY ---")
    print(f"Deterministic 1:1 Matches: {matches_1_to_1}")
    print(f"Deterministic 1:N Matches: {matches_1_to_n}")
    print(f"Deterministic N:1 Matches: {matches_n_to_1}")
    print(f"Relationship-Established-But-Semantic-Unresolved: {unresolved_cases}")
    print(f"Candidate Pools: {candidate_pools}")
    print(f"Genuine MISSING_RECORD Cases: {genuine_orphans}")
    print("Duplicate Evidence Detected:", duplicates)
    print("---------------------------------------\n")


def test_e06_arbitrary_ids_dataset_agnostic():
    """
    Regression test for E-06 proving the engine does not rely on shared 
    benchmark IDs or string prefixes (like 'E06') to establish the relationship.
    """
    import datetime
    from decimal import Decimal
    from eagle.models.canonical import CanonicalRecord
    from eagle.reconciliation.engine import reconcile
    
    source = CanonicalRecord(
        record_id="TXN-839201",
        transaction_id="TXN-839201",
        amount=Decimal("10000.00"),
        currency="INR",
        transaction_date=datetime.date(2025, 3, 10),
        settlement_date=datetime.date(2025, 3, 10),
        source="GATEWAY",
        source_reference="",
        counterparty="",
        status="SUCCESS",
        transaction_type="PAYMENT"
    )
    
    target1 = CanonicalRecord(
        record_id="SETTLE-77192",
        transaction_id="SETTLE-77192",
        amount=Decimal("6000.00"),
        currency="INR",
        transaction_date=datetime.date(2025, 3, 12),
        settlement_date=datetime.date(2025, 3, 12),
        source="BANK",
        source_reference="",
        counterparty="",
        status="SUCCESS",
        transaction_type="CREDIT"
    )
    
    target2 = CanonicalRecord(
        record_id="SETTLE-77193",
        transaction_id="SETTLE-77193",
        amount=Decimal("2500.00"),
        currency="INR",
        transaction_date=datetime.date(2025, 3, 13),
        settlement_date=datetime.date(2025, 3, 13),
        source="BANK",
        source_reference="",
        counterparty="",
        status="SUCCESS",
        transaction_type="CREDIT"
    )
    
    engine_output = reconcile([source], [target1, target2])
    results = engine_output.results
    
    assert len(results) == 1
    res = results[0]
    
    # Must be recognized as a 1:N relationship
    assert res.relationship_type.value == "1:N"
    assert res.source_record_ids == ["TXN-839201"]
    assert set(res.target_record_ids) == {"SETTLE-77192", "SETTLE-77193"}
    
    # But because there is a shortfall, it must be EXCEPTION/None for AI
    assert res.outcome.value == "EXCEPTION"
    assert res.exception_type is None
