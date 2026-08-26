import csv
import json
import os
from datetime import datetime
from decimal import Decimal
import pytest

from eagle.models.enums import ExceptionType, RelationshipType, ReconciliationOutcome
from eagle.models.ground_truth import GroundTruthDataset

DATA_DIR = os.path.join(os.path.dirname(__file__), "../data/synthetic")
GATEWAY_CSV = os.path.join(DATA_DIR, "gateway.csv")
BANK_CSV = os.path.join(DATA_DIR, "bank.csv")
GROUND_TRUTH_JSON = os.path.join(DATA_DIR, "ground_truth.json")


@pytest.fixture(scope="session")
def synthetic_data():
    gateway_records = []
    with open(GATEWAY_CSV, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            gateway_records.append(row)
            
    bank_records = []
    with open(BANK_CSV, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            bank_records.append(row)
            
    with open(GROUND_TRUTH_JSON, "r") as f:
        gt_data = json.load(f)
    
    # Validate against frozen Pydantic model
    gt_dataset = GroundTruthDataset.model_validate(gt_data)
    
    return {
        "gateway": {r["payment_id"]: r for r in gateway_records},
        "bank": {r["bank_reference"]: r for r in bank_records},
        "gt": gt_dataset
    }


def test_ground_truth_count(synthetic_data):
    # 1. Exactly 38 ground-truth relationships exist.
    assert len(synthetic_data["gt"].relationships) == 38

def test_relationship_ids(synthetic_data):
    # 2. Every relationship ID follows: R-{case_id}
    for rel in synthetic_data["gt"].relationships:
        assert rel.relationship_id.startswith("R-")
        # Ensure it matches the expected pattern, e.g., R-A01, R-E06, etc.
        case_id = rel.relationship_id[2:]
        assert len(case_id) >= 3

def test_record_existence(synthetic_data):
    # 3. Every source_record_id exists in gateway.csv.
    # 4. Every target_record_id exists in bank.csv.
    gateway_db = synthetic_data["gateway"]
    bank_db = synthetic_data["bank"]
    
    for rel in synthetic_data["gt"].relationships:
        for sid in rel.source_record_ids:
            assert sid in gateway_db
        for tid in rel.target_record_ids:
            assert tid in bank_db

def test_missing_record_convention(synthetic_data):
    # 5. No MISSING_RECORD relationship contains a fabricated ID.
    # 6. Missing-side arrays are exactly [].
    for rel in synthetic_data["gt"].relationships:
        if rel.expected_exception_type == ExceptionType.MISSING_RECORD:
            # One side must be strictly empty list, the other side must be populated and exist (tested in test_record_existence)
            assert (len(rel.source_record_ids) == 0 and len(rel.target_record_ids) > 0) or \
                   (len(rel.source_record_ids) > 0 and len(rel.target_record_ids) == 0)

def test_relationship_types(synthetic_data):
    # 7. Every relationship type is one of: 1:1, 1:N, N:1
    # 29. There are no N:M relationships.
    for rel in synthetic_data["gt"].relationships:
        assert rel.relationship_type in (RelationshipType.ONE_TO_ONE, RelationshipType.ONE_TO_MANY, RelationshipType.MANY_TO_ONE)
        if rel.relationship_type == RelationshipType.ONE_TO_ONE:
            assert len(rel.source_record_ids) <= 1 and len(rel.target_record_ids) <= 1
        elif rel.relationship_type == RelationshipType.ONE_TO_MANY:
            assert len(rel.source_record_ids) == 1 and len(rel.target_record_ids) >= 1
        elif rel.relationship_type == RelationshipType.MANY_TO_ONE:
            assert len(rel.source_record_ids) >= 1 and len(rel.target_record_ids) == 1

def test_record_uniqueness():
    # 8. Every source record ID is unique.
    # 9. Every bank record ID is unique.
    with open(GATEWAY_CSV, "r") as f:
        g_ids = [row["payment_id"] for row in csv.DictReader(f)]
    assert len(g_ids) == len(set(g_ids))
    
    with open(BANK_CSV, "r") as f:
        b_ids = [row["bank_reference"] for row in csv.DictReader(f)]
    assert len(b_ids) == len(set(b_ids))

def test_monetary_values_decimal(synthetic_data):
    # 10. Every monetary value is parseable as Decimal.
    for row in synthetic_data["gateway"].values():
        Decimal(row["amount"])
    for row in synthetic_data["bank"].values():
        Decimal(row["settlement_amount"])

def test_specific_relationship_structures(synthetic_data):
    rel_dict = {r.relationship_id: r for r in synthetic_data["gt"].relationships}
    
    # 11. C-01/C-02/C-05/E-01/E-06 actually have the specified 1:N structure.
    for r_id in ["R-C01", "R-C02", "R-C05", "R-E01", "R-E06"]:
        rel = rel_dict[r_id]
        assert rel.relationship_type == RelationshipType.ONE_TO_MANY
        assert len(rel.source_record_ids) == 1
        assert len(rel.target_record_ids) > 1

    # 12. C-03/C-04/C-06 actually have the specified N:1 structure.
    for r_id in ["R-C03", "R-C04", "R-C06"]:
        rel = rel_dict[r_id]
        assert rel.relationship_type == RelationshipType.MANY_TO_ONE
        assert len(rel.source_record_ids) > 1
        assert len(rel.target_record_ids) == 1

def _get_amounts(rel, synthetic_data):
    source_amt = sum(Decimal(synthetic_data["gateway"][sid]["amount"]) for sid in rel.source_record_ids)
    target_amt = sum(Decimal(synthetic_data["bank"][tid]["settlement_amount"]) for tid in rel.target_record_ids)
    return source_amt, target_amt

def test_exact_aggregation(synthetic_data):
    rel_dict = {r.relationship_id: r for r in synthetic_data["gt"].relationships}
    # 13. C-01/C-02/C-03/C-04 aggregate exactly.
    for r_id in ["R-C01", "R-C02", "R-C03", "R-C04"]:
        src_amt, tgt_amt = _get_amounts(rel_dict[r_id], synthetic_data)
        assert src_amt == tgt_amt

def test_tolerance_aggregation(synthetic_data):
    rel_dict = {r.relationship_id: r for r in synthetic_data["gt"].relationships}
    # 14. C-05 is within ₹1.00 tolerance.
    src_amt, tgt_amt = _get_amounts(rel_dict["R-C05"], synthetic_data)
    assert abs(src_amt - tgt_amt) <= Decimal("1.00")
    assert abs(src_amt - tgt_amt) > Decimal("0.00") # it shouldn't be exact
    
    # 15. C-06 is within ₹2.00 fee tolerance.
    src_amt, tgt_amt = _get_amounts(rel_dict["R-C06"], synthetic_data)
    assert abs(src_amt - tgt_amt) <= Decimal("2.00")
    assert abs(src_amt - tgt_amt) > Decimal("1.00") # greater than rounding tolerance

def test_e06_split_settlement_shortfall(synthetic_data):
    rel_dict = {r.relationship_id: r for r in synthetic_data["gt"].relationships}
    # 16. E-06 aggregates to exactly ₹8,500 against a ₹10,000 source.
    rel = rel_dict["R-E06"]
    src_amt, tgt_amt = _get_amounts(rel, synthetic_data)
    assert src_amt == Decimal("10000.00")
    assert tgt_amt == Decimal("8500.00")

def test_d06_partial_settlement(synthetic_data):
    rel_dict = {r.relationship_id: r for r in synthetic_data["gt"].relationships}
    # 17. D-06 is materially short and outside both tolerances.
    rel = rel_dict["R-D06"]
    src_amt, tgt_amt = _get_amounts(rel, synthetic_data)
    assert src_amt - tgt_amt > Decimal("2.00")
    assert src_amt == Decimal("10000.00")
    assert tgt_amt == Decimal("6000.00")

def test_rounding_and_fee_differences(synthetic_data):
    rel_dict = {r.relationship_id: r for r in synthetic_data["gt"].relationships}
    
    # 18. B-01 difference is exactly ₹0.50.
    s, t = _get_amounts(rel_dict["R-B01"], synthetic_data)
    assert abs(s - t) == Decimal("0.50")
    
    # 19. B-02 difference is exactly ₹0.99.
    s, t = _get_amounts(rel_dict["R-B02"], synthetic_data)
    assert abs(s - t) == Decimal("0.99")
    
    # 20. B-03 difference is exactly ₹1.50 and explicitly supported by fee evidence.
    rel_b03 = rel_dict["R-B03"]
    s_b03, t_b03 = _get_amounts(rel_b03, synthetic_data)
    assert abs(s_b03 - t_b03) == Decimal("1.50")
    bank_b03 = synthetic_data["bank"][rel_b03.target_record_ids[0]]
    assert bank_b03.get("fee") == "1.50"

    # B-04 explicit fee evidence check (gross - fee = net)
    rel_b04 = rel_dict["R-B04"]
    s_b04, t_b04 = _get_amounts(rel_b04, synthetic_data)
    gtw_b04 = synthetic_data["gateway"][rel_b04.source_record_ids[0]]
    bank_b04 = synthetic_data["bank"][rel_b04.target_record_ids[0]]
    
    assert Decimal(gtw_b04["gross_amount"]) - Decimal(gtw_b04["fee"]) == Decimal(gtw_b04["net_amount"])
    assert Decimal(gtw_b04["net_amount"]) == Decimal(bank_b04["settlement_amount"])
    assert bank_b04.get("fee") == "20.00"

def _get_settlement_delay(rel, synthetic_data):
    sid = rel.source_record_ids[0]
    tid = rel.target_record_ids[0]
    txn_date = datetime.strptime(synthetic_data["gateway"][sid]["created_at"], "%Y-%m-%d")
    stl_date = datetime.strptime(synthetic_data["bank"][tid]["posting_date"], "%Y-%m-%d")
    return (stl_date - txn_date).days

def test_settlement_delays(synthetic_data):
    rel_dict = {r.relationship_id: r for r in synthetic_data["gt"].relationships}
    # 21. B-05 settlement delay is exactly 0 days.
    assert _get_settlement_delay(rel_dict["R-B05"], synthetic_data) == 0
    # 22. B-06 settlement delay is exactly 2 days.
    assert _get_settlement_delay(rel_dict["R-B06"], synthetic_data) == 2
    # 23. B-07 settlement delay is exactly 5 days.
    assert _get_settlement_delay(rel_dict["R-B07"], synthetic_data) == 5
    # 24. B-08 settlement delay is exactly 10 days.
    assert _get_settlement_delay(rel_dict["R-B08"], synthetic_data) == 10
    
    # 25. E-04 has settlement_date before transaction_date.
    assert _get_settlement_delay(rel_dict["R-E04"], synthetic_data) < 0

def test_currency_mismatch(synthetic_data):
    rel_dict = {r.relationship_id: r for r in synthetic_data["gt"].relationships}
    # 26. D-05 currencies are INR and USD.
    rel = rel_dict["R-D05"]
    g_curr = synthetic_data["gateway"][rel.source_record_ids[0]]["currency"]
    b_curr = synthetic_data["bank"][rel.target_record_ids[0]]["currency"]
    assert g_curr == "INR"
    assert b_curr == "USD"

def test_no_data_leakage():
    # 27. No source CSV contains benchmark classification fields.
    with open(GATEWAY_CSV, "r") as f:
        headers = next(csv.reader(f))
        for h in headers:
            assert h not in ["expected_outcome", "expected_exception_type", "severity", "case_id", "relationship_id"]
    
    with open(BANK_CSV, "r") as f:
        headers = next(csv.reader(f))
        for h in headers:
            assert h not in ["expected_outcome", "expected_exception_type", "severity", "case_id", "relationship_id"]

def test_missing_records_genuinely_orphaned(synthetic_data):
    # For D-01/D-02/D-03/D-04, validate that no reasonable counterpart exists.
    gateway_db = synthetic_data["gateway"]
    bank_db = synthetic_data["bank"]
    
    rel_dict = {r.relationship_id: r for r in synthetic_data["gt"].relationships}
    
    # Check D-01 (GTW-D01)
    g1 = gateway_db[rel_dict["R-D01"].source_record_ids[0]]
    assert not any(Decimal(b["settlement_amount"]) == Decimal(g1["amount"]) for b in bank_db.values())

    # Check D-02 (GTW-D02)
    g2 = gateway_db[rel_dict["R-D02"].source_record_ids[0]]
    assert not any(Decimal(b["settlement_amount"]) == Decimal(g2["amount"]) for b in bank_db.values())

    # Check D-03 (BANK-ORPH-001)
    b3 = bank_db[rel_dict["R-D03"].target_record_ids[0]]
    assert b3["bank_reference"] == "BANK-ORPH-001"
    assert not any(Decimal(g["amount"]) == Decimal(b3["settlement_amount"]) for g in gateway_db.values())

    # Check D-04 (BANK-D04)
    b4 = bank_db[rel_dict["R-D04"].target_record_ids[0]]
    assert not any(Decimal(g["amount"]) == Decimal(b4["settlement_amount"]) for g in gateway_db.values())

def test_e03_ambiguity(synthetic_data):
    rel_dict = {r.relationship_id: r for r in synthetic_data["gt"].relationships}
    rel_e03 = rel_dict["R-E03"]
    gtw_e03 = synthetic_data["gateway"][rel_e03.source_record_ids[0]]
    
    # Ensure there's no exact reference match with E-03
    for b in synthetic_data["bank"].values():
        if b["bank_reference"] in rel_e03.target_record_ids or b["bank_reference"] == "BANK-D03":
            assert b["narration"] != gtw_e03["merchant_txn_ref"]
            
    # There should be at least two candidates with same amount and close dates
    candidates = []
    for b in synthetic_data["bank"].values():
        if Decimal(b["settlement_amount"]) == Decimal(gtw_e03["amount"]):
            if b["currency"] == gtw_e03["currency"]:
                # Assume dates are close enough for this test
                candidates.append(b)
    
    # Should at least be BANK-E03 and BANK-D03
    assert len(candidates) >= 2
    
    # Ensure the correct target is one of the candidates
    target_ids = [c["bank_reference"] for c in candidates]
    assert rel_e03.target_record_ids[0] in target_ids

def test_a05_a06_counterparty_evidence(synthetic_data):
    rel_dict = {r.relationship_id: r for r in synthetic_data["gt"].relationships}
    
    # A-05
    rel_a05 = rel_dict["R-A05"]
    gtw_a05 = synthetic_data["gateway"][rel_a05.source_record_ids[0]]
    bank_a05 = synthetic_data["bank"][rel_a05.target_record_ids[0]]
    assert gtw_a05.get("merchant_name") == bank_a05.get("counterparty")
    assert gtw_a05.get("merchant_name") is not None
    
    # A-06
    rel_a06 = rel_dict["R-A06"]
    gtw_a06 = synthetic_data["gateway"][rel_a06.source_record_ids[0]]
    bank_a06 = synthetic_data["bank"][rel_a06.target_record_ids[0]]
    assert gtw_a06.get("merchant_name") == bank_a06.get("counterparty")
    assert gtw_a06.get("merchant_name") is not None

def test_d03_and_decoy_isolation(synthetic_data):
    # 1. BANK-D03 participates in NO ground-truth relationship (it is purely a decoy for E-03)
    # 2. BANK-ORPH-001 participates in R-D03 only.
    
    bank_d03_in_gt = False
    bank_orph_count = 0
    
    for rel in synthetic_data["gt"].relationships:
        if "BANK-D03" in rel.target_record_ids:
            bank_d03_in_gt = True
        if "BANK-ORPH-001" in rel.target_record_ids:
            bank_orph_count += 1
            assert rel.relationship_id == "R-D03"
            
    assert not bank_d03_in_gt, "BANK-D03 should be a pure decoy and not in ground truth"
    assert bank_orph_count == 1, "BANK-ORPH-001 must appear exactly once in ground truth"

def test_d07_duplicate_evidence(synthetic_data):
    # 6. D-07 duplicate evidence remains valid.
    # D-07 has same payment reference, amount, and date as A-01, but a different payment_id
    rel_dict = {r.relationship_id: r for r in synthetic_data["gt"].relationships}
    
    a01 = synthetic_data["gateway"][rel_dict["R-A01"].source_record_ids[0]]
    d07 = synthetic_data["gateway"][rel_dict["R-D07"].source_record_ids[0]]
    
    # Must be different physical records
    assert a01["payment_id"] != d07["payment_id"]
    
    # Must share exact evidence
    assert a01["merchant_txn_ref"] == d07["merchant_txn_ref"]
    assert a01["amount"] == d07["amount"]
    assert a01["created_at"] == d07["created_at"]

