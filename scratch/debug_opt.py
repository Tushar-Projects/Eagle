"""Debug Option evaluation for S-1."""
from datetime import date
from decimal import Decimal
from eagle.models.canonical import CanonicalRecord
from eagle.models.evidence import CandidateRelationshipOption, CandidateRelationshipEvidence
from eagle.rules.models import ReconciliationRule
from eagle.rules.rule_engine import RuleEngine

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

src_lookup = {"S-1": s1}
tgt_lookup = {"T-1": t1, "T-2": t2, "T-3": t3}

rule = ReconciliationRule(
    rule_id="RULE-1",
    name="Rule 1",
    description="Desc",
    source_counterparty_pattern="Merchant Agg",
    max_amount_difference=Decimal("0.00"),
    max_settlement_delay_days=1,
    created_at="2025-01-01T00:00:00Z",
)

opt1 = CandidateRelationshipOption(source_record_ids=["S-1"], target_record_ids=["T-1", "T-2"])
opt2 = CandidateRelationshipOption(source_record_ids=["S-1"], target_record_ids=["T-1", "T-3"])

m1, s1 = RuleEngine._evaluate_option(rule, opt1, src_lookup, tgt_lookup)
m2, s2 = RuleEngine._evaluate_option(rule, opt2, src_lookup, tgt_lookup)

print(f"Opt 1 match: {m1}, spec: {s1}")
print(f"Opt 2 match: {m2}, spec: {s2}")
