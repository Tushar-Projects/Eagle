"""Test updated _evaluate_option logic."""
from datetime import date
from decimal import Decimal
from eagle.models.canonical import CanonicalRecord
from eagle.models.evidence import CandidateRelationshipOption
from eagle.rules.models import ReconciliationRule

def evaluate_option_fixed(rule, option, source_lookup, target_lookup):
    src_records = [source_lookup[sid] for sid in option.source_record_ids if sid in source_lookup]
    tgt_records = [target_lookup[tid] for tid in option.target_record_ids if tid in target_lookup]

    if not src_records and not tgt_records:
        return False, 0

    specificity = 0

    # 1. Counterparty Predicate
    if rule.source_counterparty_pattern is not None:
        pattern = rule.source_counterparty_pattern.strip().lower()
        # All source records providing counterparty must match pattern
        for s in src_records:
            if s.counterparty and pattern not in s.counterparty.strip().lower():
                return False, 0
        # All target records providing counterparty must match pattern
        for t in tgt_records:
            if t.counterparty and pattern not in t.counterparty.strip().lower():
                return False, 0
        # At least one record must have matched
        matched_any = any(s.counterparty and pattern in s.counterparty.strip().lower() for s in src_records) or \
                      any(t.counterparty and pattern in t.counterparty.strip().lower() for t in tgt_records)
        if not matched_any:
            return False, 0
        specificity += 1

    # 2. Reference Prefix Predicate
    if rule.reference_prefix is not None:
        prefix = rule.reference_prefix.strip().lower()
        has_ref = any(
            s.source_reference and s.source_reference.strip().lower().startswith(prefix)
            for s in src_records
        )
        if not has_ref:
            return False, 0
        specificity += 1

    # 3. Currency Predicate
    if rule.currency is not None:
        curr = rule.currency.strip().upper()
        all_records = src_records + tgt_records
        if not all(r.currency and r.currency.strip().upper() == curr for r in all_records):
            return False, 0
        specificity += 1

    # 4. Amount Difference Predicate
    if rule.max_amount_difference is not None:
        if not src_records or not tgt_records:
            return False, 0
        total_src = sum((s.amount for s in src_records), Decimal("0.00"))
        total_tgt = sum((t.amount for t in tgt_records), Decimal("0.00"))
        diff = abs(total_src - total_tgt)
        if diff > rule.max_amount_difference:
            return False, 0
        specificity += 1

    # 5. Settlement Delay Predicate
    if rule.max_settlement_delay_days is not None:
        if not src_records or not tgt_records:
            return False, 0
        min_src_date = min(s.transaction_date for s in src_records)
        max_tgt_date = max(t.settlement_date for t in tgt_records)
        delay = (max_tgt_date - min_src_date).days
        if delay > rule.max_settlement_delay_days:
            return False, 0
        specificity += 1

    return True, specificity

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

m1, spec1 = evaluate_option_fixed(rule, opt1, src_lookup, tgt_lookup)
m2, spec2 = evaluate_option_fixed(rule, opt2, src_lookup, tgt_lookup)

print(f"Opt 1 match: {m1}, spec: {spec1}")
print(f"Opt 2 match: {m2}, spec: {spec2}")
