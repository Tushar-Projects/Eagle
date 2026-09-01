"""Test what record configurations produce CandidateRelationshipEvidence."""

from datetime import date
from decimal import Decimal
from eagle.models.canonical import CanonicalRecord
from eagle.reconciliation.engine import reconcile

def test_cases():
    # Case 1: Stage 5 Aggregation with ambiguity (1 source, 2 bank targets)
    # Source = 10000, Bank 1 = 6000, Bank 2 = 4000, Bank 3 = 4000 (decoy)
    s1 = CanonicalRecord(
        record_id="S-1", transaction_id="S-1", source="GATEWAY", source_reference="REF-AGG",
        amount=Decimal("10000.00"), currency="INR", transaction_date=date(2025, 1, 1),
        settlement_date=date(2025, 1, 1), counterparty="Merchant Agg", status="COMPLETED", transaction_type="CREDIT"
    )
    t1 = CanonicalRecord(
        record_id="T-1", transaction_id="T-1", source="BANK", source_reference="BNK-1",
        amount=Decimal("6000.00"), currency="INR", transaction_date=date(2025, 1, 2),
        settlement_date=date(2025, 1, 2), counterparty="Merchant Agg", status="POSTED", transaction_type="CREDIT"
    )
    t2 = CanonicalRecord(
        record_id="T-2", transaction_id="T-2", source="BANK", source_reference="BNK-2",
        amount=Decimal("4000.00"), currency="INR", transaction_date=date(2025, 1, 2),
        settlement_date=date(2025, 1, 2), counterparty="Merchant Agg", status="POSTED", transaction_type="CREDIT"
    )
    t3 = CanonicalRecord(
        record_id="T-3", transaction_id="T-3", source="BANK", source_reference="BNK-3",
        amount=Decimal("4000.00"), currency="INR", transaction_date=date(2025, 1, 2),
        settlement_date=date(2025, 1, 2), counterparty="Other Merchant", status="POSTED", transaction_type="CREDIT"
    )

    out = reconcile([s1], [t1, t2, t3])
    print(f"Results: {len(out.results)}")
    for r in out.results:
        print(f"  Result: {r.relationship_id}, outcome={r.outcome}, ex={r.exception_type}, src={r.source_record_ids}, tgt={r.target_record_ids}")
    print(f"Candidates: {len(out.candidates)}")
    for c in out.candidates:
        print(f"  Context: {c.relationship_context}")
        for opt in c.candidate_options:
            print(f"    Opt: src={opt.source_record_ids}, tgt={opt.target_record_ids}")

if __name__ == "__main__":
    test_cases()
