"""Tests for the deterministic reconciliation engine."""
import csv
from datetime import datetime
from decimal import Decimal

from eagle.models.canonical import CanonicalRecord
from eagle.models.enums import ExceptionType, ReconciliationOutcome, RelationshipType, Severity
from eagle.reconciliation.engine import reconcile

GATEWAY_CSV = "data/synthetic/gateway.csv"
BANK_CSV = "data/synthetic/bank.csv"

from eagle.evaluation.data_loader import load_bank_records, load_gateway_records

def test_engine_deterministic_resolution():
    sources = load_gateway_records(GATEWAY_CSV)
    targets = load_bank_records(BANK_CSV)
    
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

    # 9. 1:N Aggregation Match Ambiguity (C-01, C-02, C-05 are now candidate pools due to multiple valid subsets)
    assert "GTW-C01" not in source_map
    assert "GTW-C02" not in source_map
    
    # 10. N:1 Aggregation Match Ambiguity (C-03, C-04, C-06 are now candidate pools due to multiple valid subsets)
    assert "GTW-C03-1" not in source_map
    assert "GTW-C04-1" not in source_map
    
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
    e03_candidates = [c for c in candidates if c.candidate_options[0].source_record_ids == ["GTW-E03"]]
    assert len(e03_candidates) == 1
    e03_evidence = e03_candidates[0]
    e03_targets = {opt.target_record_ids[0] for opt in e03_evidence.candidate_options}
    assert e03_targets == {"BANK-E03", "BANK-D03"}
    # Must not be represented as 1:1 or 1:N in the relationship type field (it doesn't have one)
    assert not hasattr(e03_evidence, "relationship_type")
    
    # Verify C-02/C-05 1:N Ambiguity representation
    c02_candidates = [c for c in candidates if c.candidate_options[0].source_record_ids == ["GTW-C02"]]
    assert len(c02_candidates) == 1
    c02_targets = [set(opt.target_record_ids) for opt in c02_candidates[0].candidate_options]
    assert {"BANK-C02-1", "BANK-C02-2", "BANK-C02-3"} in c02_targets
    assert {"BANK-C05-1", "BANK-C05-2"} in c02_targets
    assert {"BANK-C03"} in c02_targets
    assert {"BANK-C04"} in c02_targets
    
    # Verify C-04/C-06 N:1 Ambiguity representation
    c04_candidates = [c for c in candidates if c.candidate_options[0].target_record_ids == ["BANK-C04"]]
    assert len(c04_candidates) == 1
    c04_sources = [set(opt.source_record_ids) for opt in c04_candidates[0].candidate_options]
    assert {"GTW-C04-1", "GTW-C04-2", "GTW-C04-3"} in c04_sources
    assert {"GTW-C04-2", "GTW-C06-2"} in c04_sources
    
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


# ---------------------------------------------------------------------------
# Regression tests for Anchor-Based Decision Groups (Chunk 3 Stage 5 Correction)
# ---------------------------------------------------------------------------


def test_candidate_options_are_unique():
    """Verify that every CandidateRelationshipOption within every decision group is unique."""
    sources = load_gateway_records(GATEWAY_CSV)
    targets = load_bank_records(BANK_CSV)
    engine_output = reconcile(sources, targets)

    for group in engine_output.candidates:
        seen_keys = set()
        for opt in group.candidate_options:
            key = (tuple(sorted(opt.source_record_ids)), tuple(sorted(opt.target_record_ids)))
            assert key not in seen_keys, f"Duplicate option found in group: {key}"
            seen_keys.add(key)
            # Verify unique participant IDs within option
            assert len(opt.source_record_ids) == len(set(opt.source_record_ids))
            assert len(opt.target_record_ids) == len(set(opt.target_record_ids))
            # Verify no N:M topology
            assert not (len(opt.source_record_ids) > 1 and len(opt.target_record_ids) > 1)


def test_candidate_group_order_is_deterministic():
    """Verify that identical inputs produce identical candidate groups and options across multiple runs."""
    sources = load_gateway_records(GATEWAY_CSV)
    targets = load_bank_records(BANK_CSV)

    run1 = reconcile(sources, targets)
    run2 = reconcile(sources, targets)

    assert len(run1.candidates) == len(run2.candidates)
    for g1, g2 in zip(run1.candidates, run2.candidates):
        assert g1.relationship_context == g2.relationship_context
        assert len(g1.candidate_options) == len(g2.candidate_options)
        for opt1, opt2 in zip(g1.candidate_options, g2.candidate_options):
            assert opt1.source_record_ids == opt2.source_record_ids
            assert opt1.target_record_ids == opt2.target_record_ids


def test_same_source_1_to_1_alternatives_share_one_group():
    """Verify that competing 1:1 alternatives for the same source are grouped into one source-anchored decision group."""
    sources = load_gateway_records(GATEWAY_CSV)
    targets = load_bank_records(BANK_CSV)
    engine_output = reconcile(sources, targets)

    e03_groups = [g for g in engine_output.candidates if any("GTW-E03" in opt.source_record_ids for opt in g.candidate_options)]
    assert len(e03_groups) == 1, "GTW-E03 must have exactly one decision group"
    group = e03_groups[0]
    for opt in group.candidate_options:
        assert opt.source_record_ids == ["GTW-E03"]


def test_same_source_1_to_n_alternatives_share_one_group():
    """Verify that competing 1:N alternatives for the same source are grouped into one source-anchored decision group."""
    sources = load_gateway_records(GATEWAY_CSV)
    targets = load_bank_records(BANK_CSV)
    engine_output = reconcile(sources, targets)

    c05_groups = [g for g in engine_output.candidates if any("GTW-C05" in opt.source_record_ids for opt in g.candidate_options)]
    assert len(c05_groups) == 1, "GTW-C05 must have exactly one decision group"
    group = c05_groups[0]
    for opt in group.candidate_options:
        assert opt.source_record_ids == ["GTW-C05"]


def test_cross_cardinality_alternatives_share_one_source_group():
    """Verify that competing 1:1 and 1:N alternatives for the same source share one source-anchored group."""
    sources = load_gateway_records(GATEWAY_CSV)
    targets = load_bank_records(BANK_CSV)
    engine_output = reconcile(sources, targets)

    c02_groups = [g for g in engine_output.candidates if any("GTW-C02" in opt.source_record_ids for opt in g.candidate_options)]
    assert len(c02_groups) == 1, "GTW-C02 must have exactly one decision group"
    group = c02_groups[0]

    # Has 1:N options (multiple targets)
    has_1_to_n = any(len(opt.target_record_ids) > 1 for opt in group.candidate_options)
    # Has 1:1 options (single target)
    has_1_to_1 = any(len(opt.target_record_ids) == 1 for opt in group.candidate_options)
    assert has_1_to_n and has_1_to_1, "GTW-C02 group must contain both 1:1 and 1:N alternatives"


def test_same_target_n_to_1_alternatives_share_one_group():
    """Verify that competing N:1 source combinations for the same target share one target-anchored group."""
    sources = load_gateway_records(GATEWAY_CSV)
    targets = load_bank_records(BANK_CSV)
    engine_output = reconcile(sources, targets)

    c03_groups = [g for g in engine_output.candidates if all(opt.target_record_ids == ["BANK-C03"] for opt in g.candidate_options)]
    assert len(c03_groups) == 1, "BANK-C03 must have exactly one target-anchored decision group"
    group = c03_groups[0]
    for opt in group.candidate_options:
        assert opt.target_record_ids == ["BANK-C03"]
        assert len(opt.source_record_ids) > 1, "Must be N:1 options"


def test_transitive_overlap_does_not_collapse_groups():
    """Verify that transitively overlapping alternatives do NOT collapse into a single giant connected component."""
    sources = load_gateway_records(GATEWAY_CSV)
    targets = load_bank_records(BANK_CSV)
    engine_output = reconcile(sources, targets)

    # C-02 (source-anchored), C-05 (source-anchored), C-03 (target-anchored), C-04 (target-anchored)
    # must be separate CandidateRelationshipEvidence instances
    c02_groups = [g for g in engine_output.candidates if all(opt.source_record_ids == ["GTW-C02"] for opt in g.candidate_options)]
    c05_groups = [g for g in engine_output.candidates if all(opt.source_record_ids == ["GTW-C05"] for opt in g.candidate_options)]
    c03_groups = [g for g in engine_output.candidates if all(opt.target_record_ids == ["BANK-C03"] for opt in g.candidate_options)]
    c04_groups = [g for g in engine_output.candidates if all(opt.target_record_ids == ["BANK-C04"] for opt in g.candidate_options)]

    assert len(c02_groups) == 1
    assert len(c05_groups) == 1
    assert len(c03_groups) == 1
    assert len(c04_groups) == 1
    # Verify they are all distinct instances
    assert len({id(c02_groups[0]), id(c05_groups[0]), id(c03_groups[0]), id(c04_groups[0])}) == 4


def test_option_belongs_to_only_one_decision_group():
    """Verify that no CandidateRelationshipOption is duplicated across multiple decision groups."""
    sources = load_gateway_records(GATEWAY_CSV)
    targets = load_bank_records(BANK_CSV)
    engine_output = reconcile(sources, targets)

    seen_options = set()
    for group in engine_output.candidates:
        for opt in group.candidate_options:
            key = (tuple(sorted(opt.source_record_ids)), tuple(sorted(opt.target_record_ids)))
            assert key not in seen_options, f"Option {key} appears in multiple decision groups!"
            seen_options.add(key)


def test_stage1_to_stage4_matches_are_not_replaced():
    """Verify that deterministic Stage 1-4 committed matches are never replaced by Stage 5 aggregation."""
    sources = load_gateway_records(GATEWAY_CSV)
    targets = load_bank_records(BANK_CSV)
    engine_output = reconcile(sources, targets)

    committed_sources = {r.source_record_ids[0] for r in engine_output.results if r.source_record_ids}
    assert "GTW-A01" in committed_sources
    assert "GTW-A04" in committed_sources
    assert "GTW-A05" in committed_sources
    assert "GTW-B01" in committed_sources
    assert "GTW-B04" in committed_sources

    # None of these committed records may appear in any candidate option
    candidate_sources = {sid for g in engine_output.candidates for opt in g.candidate_options for sid in opt.source_record_ids}
    assert not ({"GTW-A01", "GTW-A04", "GTW-A05", "GTW-B01", "GTW-B04"} & candidate_sources)


def test_candidate_records_are_not_marked_missing():
    """Verify that records participating in candidate options are NOT prematurely emitted as MISSING_RECORD."""
    sources = load_gateway_records(GATEWAY_CSV)
    targets = load_bank_records(BANK_CSV)
    engine_output = reconcile(sources, targets)

    missing_sources = {
        r.source_record_ids[0] for r in engine_output.results
        if r.exception_type == ExceptionType.MISSING_RECORD and r.source_record_ids
    }
    missing_targets = {
        r.target_record_ids[0] for r in engine_output.results
        if r.exception_type == ExceptionType.MISSING_RECORD and r.target_record_ids
    }

    candidate_sources = {sid for g in engine_output.candidates for opt in g.candidate_options for sid in opt.source_record_ids}
    candidate_targets = {tid for g in engine_output.candidates for opt in g.candidate_options for tid in opt.target_record_ids}

    assert not (missing_sources & candidate_sources), "Candidate source records marked as MISSING_RECORD!"
    assert not (missing_targets & candidate_targets), "Candidate target records marked as MISSING_RECORD!"


def test_missing_record_amount_is_zero():
    """Verify that all MISSING_RECORD exceptions have reconciled_amount equal to Decimal('0.00')."""
    sources = load_gateway_records(GATEWAY_CSV)
    targets = load_bank_records(BANK_CSV)
    engine_output = reconcile(sources, targets)

    missing_records = [r for r in engine_output.results if r.exception_type == ExceptionType.MISSING_RECORD]
    assert len(missing_records) > 0
    for r in missing_records:
        assert r.reconciled_amount == Decimal("0.00"), f"MISSING_RECORD has non-zero amount: {r.reconciled_amount}"


def test_d08_e03_candidate_pools_remain_isolated():
    """Verify that GTW-D08 and GTW-E03 are isolated into their own source-anchored decision groups."""
    sources = load_gateway_records(GATEWAY_CSV)
    targets = load_bank_records(BANK_CSV)
    engine_output = reconcile(sources, targets)

    d08_groups = [g for g in engine_output.candidates if all(opt.source_record_ids == ["GTW-D08"] for opt in g.candidate_options)]
    e03_groups = [g for g in engine_output.candidates if all(opt.source_record_ids == ["GTW-E03"] for opt in g.candidate_options)]

    assert len(d08_groups) == 1
    assert len(e03_groups) == 1
    assert id(d08_groups[0]) != id(e03_groups[0]), "D-08 and E-03 must NOT be merged into one group"


def test_c02_c05_candidate_groups_are_anchor_based():
    """Verify C-02 and C-05 are independent source-anchored decision groups."""
    sources = load_gateway_records(GATEWAY_CSV)
    targets = load_bank_records(BANK_CSV)
    engine_output = reconcile(sources, targets)

    c02_groups = [g for g in engine_output.candidates if all(opt.source_record_ids == ["GTW-C02"] for opt in g.candidate_options)]
    c05_groups = [g for g in engine_output.candidates if all(opt.source_record_ids == ["GTW-C05"] for opt in g.candidate_options)]

    assert len(c02_groups) == 1
    assert len(c05_groups) == 1
    assert id(c02_groups[0]) != id(c05_groups[0])
    for opt in c02_groups[0].candidate_options:
        assert opt.source_record_ids == ["GTW-C02"]
    for opt in c05_groups[0].candidate_options:
        assert opt.source_record_ids == ["GTW-C05"]


def test_c03_c04_candidate_groups_are_anchor_based():
    """Verify C-03 and C-04 are independent target-anchored decision groups."""
    sources = load_gateway_records(GATEWAY_CSV)
    targets = load_bank_records(BANK_CSV)
    engine_output = reconcile(sources, targets)

    c03_groups = [g for g in engine_output.candidates if all(opt.target_record_ids == ["BANK-C03"] for opt in g.candidate_options)]
    c04_groups = [g for g in engine_output.candidates if all(opt.target_record_ids == ["BANK-C04"] for opt in g.candidate_options)]

    assert len(c03_groups) == 1
    assert len(c04_groups) == 1
    assert id(c03_groups[0]) != id(c04_groups[0])
    for opt in c03_groups[0].candidate_options:
        assert opt.target_record_ids == ["BANK-C03"]
    for opt in c04_groups[0].candidate_options:
        assert opt.target_record_ids == ["BANK-C04"]


def test_c06_n_to_1_fee_candidate_generated():
    """Verify that [GTW-C06-1, GTW-C06-2] -> [BANK-C06] is generated as a valid N:1 fee candidate."""
    sources = load_gateway_records(GATEWAY_CSV)
    targets = load_bank_records(BANK_CSV)
    engine_output = reconcile(sources, targets)

    # 1. Locate the target-anchored candidate group for BANK-C06
    c06_groups = [g for g in engine_output.candidates if all(opt.target_record_ids == ["BANK-C06"] for opt in g.candidate_options)]
    assert len(c06_groups) == 1, "BANK-C06 must have exactly one target-anchored candidate group"
    group = c06_groups[0]

    # 2. Find the specific option [GTW-C06-1, GTW-C06-2] -> [BANK-C06]
    c06_options = [
        opt for opt in group.candidate_options
        if set(opt.source_record_ids) == {"GTW-C06-1", "GTW-C06-2"} and opt.target_record_ids == ["BANK-C06"]
    ]
    assert len(c06_options) == 1, "The C-06 candidate option must be present in the candidate group"
    opt = c06_options[0]

    # 3. Verify topology is N:1
    assert len(opt.source_record_ids) == 2
    assert len(opt.target_record_ids) == 1
    assert sorted(opt.source_record_ids) == ["GTW-C06-1", "GTW-C06-2"]
    assert opt.target_record_ids == ["BANK-C06"]

    # 4. Verify financial amounts and difference
    src_lookup = {s.record_id: s for s in sources}
    tgt_lookup = {t.record_id: t for t in targets}
    source_sum = sum(src_lookup[sid].amount for sid in opt.source_record_ids)
    target_amt = tgt_lookup[opt.target_record_ids[0]].amount
    diff = source_sum - target_amt

    assert source_sum == Decimal("10000.00")
    assert target_amt == Decimal("9998.50")
    assert diff == Decimal("1.50")

    # 5. Verify BANK-C06 is NOT emitted as MISSING_RECORD in deterministic engine results
    missing_targets = [
        r.target_record_ids[0] for r in engine_output.results
        if r.exception_type == ExceptionType.MISSING_RECORD and r.target_record_ids
    ]
    assert "BANK-C06" not in missing_targets, "BANK-C06 must not be emitted as MISSING_RECORD when valid candidates exist"


def test_n_to_1_discrepancy_larger_than_fee_tolerance_rejected():
    """Verify that an N:1 discrepancy larger than FEE_MATCH_TOLERANCE is NOT accepted as a fee aggregation."""
    from eagle.reconciliation.aggregation import find_n_to_1_match
    import datetime

    src1 = CanonicalRecord(
        record_id="SRC-1",
        transaction_id="TXN-1",
        account_id="ACC",
        amount=Decimal("5000.00"),
        currency="INR",
        transaction_date=datetime.date(2025, 2, 10),
        settlement_date=datetime.date(2025, 2, 10),
        source="GATEWAY",
        source_reference="",
        counterparty="",
        status="SUCCESS",
        transaction_type="DEBIT",
    )
    src2 = CanonicalRecord(
        record_id="SRC-2",
        transaction_id="TXN-2",
        account_id="ACC",
        amount=Decimal("5000.00"),
        currency="INR",
        transaction_date=datetime.date(2025, 2, 10),
        settlement_date=datetime.date(2025, 2, 10),
        source="GATEWAY",
        source_reference="",
        counterparty="",
        status="SUCCESS",
        transaction_type="DEBIT",
    )
    # Target amount is 9800.00 -> source total (10000.00) - target (9800.00) = 200.00 > FEE_MATCH_TOLERANCE (100.00)
    tgt_excessive_fee = CanonicalRecord(
        record_id="TGT-EXCESS",
        transaction_id="TXN-TGT-EXCESS",
        account_id="ACC",
        amount=Decimal("9800.00"),
        currency="INR",
        transaction_date=datetime.date(2025, 2, 12),
        settlement_date=datetime.date(2025, 2, 12),
        source="BANK",
        source_reference="",
        counterparty="",
        status="SUCCESS",
        transaction_type="CREDIT",
    )

    matches = find_n_to_1_match([src1, src2], tgt_excessive_fee)
    # Must not match as exact, rounding, or fee
    fee_matches = [m for m in matches if m[2] is True]
    exact_or_rounding_matches = [m for m in matches if m[1] is True or (m[1] is False and m[2] is False and m[3] is False)]
    assert len(fee_matches) == 0, "Discrepancy of 200.00 must not be accepted as a fee match (tolerance is 100.00)"
    assert len(exact_or_rounding_matches) == 0


