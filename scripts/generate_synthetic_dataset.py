import csv
import json
import os
from decimal import Decimal

def add_case(
    gateway_records, bank_records, ground_truth,
    case_id, rel_type, gateway_data, bank_data, outcome, exception_type=None, reconciled_amount=None, notes=""
):
    g_ids = []
    for g in gateway_data:
        if "payment_id" not in g:
            g["payment_id"] = f"GTW-{case_id}"
        g_ids.append(g["payment_id"])
        gateway_records.append(g)
        
    b_ids = []
    for b in bank_data:
        if "bank_reference" not in b:
            b["bank_reference"] = f"BANK-{case_id}"
        b_ids.append(b["bank_reference"])
        bank_records.append(b)
        
    ground_truth.append({
        "relationship_id": f"R-{case_id.replace('-', '')}",
        "relationship_type": rel_type,
        "source_record_ids": g_ids,
        "target_record_ids": b_ids,
        "expected_outcome": outcome,
        "expected_exception_type": exception_type,
        "expected_reconciled_amount": str(reconciled_amount) if reconciled_amount is not None else "0.00",
        "notes": notes
    })

def generate_dataset():
    gateway_records = []
    bank_records = []
    ground_truth = []
    
    # A-01 Exact ID match — standard payment
    add_case(gateway_records, bank_records, ground_truth, "A-01", "1:1",
        [{"payment_id": "GTW-A01", "amount": "5000.00", "currency": "INR", "created_at": "2025-01-15", "merchant_txn_ref": "PAY-10001"}],
        [{"bank_reference": "BANK-A01", "settlement_amount": "5000.00", "currency": "INR", "posting_date": "2025-01-17", "narration": "PAY-10001"}],
        "MATCHED", reconciled_amount="5000.00"
    )

    # A-02 Exact reference match — refund
    add_case(gateway_records, bank_records, ground_truth, "A-02", "1:1",
        [{"payment_id": "GTW-A02", "amount": "-1500.00", "currency": "INR", "created_at": "2025-01-16", "merchant_txn_ref": "REF-992"}],
        [{"bank_reference": "BANK-A02", "settlement_amount": "-1500.00", "currency": "INR", "posting_date": "2025-01-18", "narration": "REF-992"}],
        "MATCHED", reconciled_amount="-1500.00"
    )

    # A-03 Normalized ID — case difference
    add_case(gateway_records, bank_records, ground_truth, "A-03", "1:1",
        [{"payment_id": "GTW-A03", "amount": "2000.00", "currency": "INR", "created_at": "2025-01-15", "merchant_txn_ref": "PAY-1001"}],
        [{"bank_reference": "BANK-A03", "settlement_amount": "2000.00", "currency": "INR", "posting_date": "2025-01-17", "narration": "pay-1001"}],
        "MATCHED", reconciled_amount="2000.00"
    )

    # A-04 Normalized ID — prefix/format
    add_case(gateway_records, bank_records, ground_truth, "A-04", "1:1",
        [{"payment_id": "GTW-A04", "amount": "2100.00", "currency": "INR", "created_at": "2025-01-15", "merchant_txn_ref": "pay_ABC123"}],
        [{"bank_reference": "BANK-A04", "settlement_amount": "2100.00", "currency": "INR", "posting_date": "2025-01-17", "narration": "PAY_abc123"}],
        "MATCHED", reconciled_amount="2100.00"
    )

    # A-05 Amount/date/currency match — no ID overlap
    add_case(gateway_records, bank_records, ground_truth, "A-05", "1:1",
        [{"payment_id": "GTW-A05", "amount": "3450.00", "currency": "INR", "created_at": "2025-01-20", "merchant_txn_ref": "INT-9991", "merchant_name": "ACME Corp"}],
        [{"bank_reference": "BANK-A05", "settlement_amount": "3450.00", "currency": "INR", "posting_date": "2025-01-22", "narration": "EXT-8882", "counterparty": "ACME Corp"}],
        "MATCHED", reconciled_amount="3450.00"
    )

    # A-06 Amount/date match — different reference formats
    add_case(gateway_records, bank_records, ground_truth, "A-06", "1:1",
        [{"payment_id": "GTW-A06", "amount": "4400.00", "currency": "INR", "created_at": "2025-01-21", "merchant_txn_ref": "T-112233", "merchant_name": "Globex"}],
        [{"bank_reference": "BANK-A06", "settlement_amount": "4400.00", "currency": "INR", "posting_date": "2025-01-23", "narration": "X112233", "counterparty": "Globex"}],
        "MATCHED", reconciled_amount="4400.00"
    )

    # A-07 Exact match — all optional fields populated
    add_case(gateway_records, bank_records, ground_truth, "A-07", "1:1",
        [{"payment_id": "GTW-A07", "amount": "5000.00", "currency": "INR", "created_at": "2025-01-15", "merchant_txn_ref": "PAY-A07", "gross_amount": "5100.00", "fee": "100.00", "net_amount": "5000.00"}],
        [{"bank_reference": "BANK-A07", "settlement_amount": "5000.00", "currency": "INR", "posting_date": "2025-01-17", "narration": "PAY-A07"}],
        "MATCHED", reconciled_amount="5000.00"
    )

    # A-08 Exact match — large transaction
    add_case(gateway_records, bank_records, ground_truth, "A-08", "1:1",
        [{"payment_id": "GTW-A08", "amount": "150000.50", "currency": "INR", "created_at": "2025-01-15", "merchant_txn_ref": "PAY-A08"}],
        [{"bank_reference": "BANK-A08", "settlement_amount": "150000.50", "currency": "INR", "posting_date": "2025-01-17", "narration": "PAY-A08"}],
        "MATCHED", reconciled_amount="150000.50"
    )

    # B-01 Rounding difference — ₹0.50
    add_case(gateway_records, bank_records, ground_truth, "B-01", "1:1",
        [{"payment_id": "GTW-B01", "amount": "1000.00", "currency": "INR", "created_at": "2025-01-15", "merchant_txn_ref": "PAY-B01"}],
        [{"bank_reference": "BANK-B01", "settlement_amount": "999.50", "currency": "INR", "posting_date": "2025-01-17", "narration": "PAY-B01"}],
        "MATCHED", "ROUNDING_DIFFERENCE", reconciled_amount="1000.00"
    )

    # B-02 Rounding difference — ₹0.99
    add_case(gateway_records, bank_records, ground_truth, "B-02", "1:1",
        [{"payment_id": "GTW-B02", "amount": "1000.00", "currency": "INR", "created_at": "2025-01-15", "merchant_txn_ref": "PAY-B02"}],
        [{"bank_reference": "BANK-B02", "settlement_amount": "999.01", "currency": "INR", "posting_date": "2025-01-17", "narration": "PAY-B02"}],
        "MATCHED", "ROUNDING_DIFFERENCE", reconciled_amount="1000.00"
    )

    # B-03 Fee deduction — ₹1.50
    add_case(gateway_records, bank_records, ground_truth, "B-03", "1:1",
        [{"payment_id": "GTW-B03", "amount": "1000.00", "currency": "INR", "created_at": "2025-01-15", "merchant_txn_ref": "PAY-B03"}],
        [{"bank_reference": "BANK-B03", "settlement_amount": "998.50", "currency": "INR", "posting_date": "2025-01-17", "narration": "PAY-B03", "fee": "1.50"}],
        "MATCHED", "FEE_DEDUCTION", reconciled_amount="1000.00"
    )

    # B-04 Fee deduction — with gross/fee/net
    add_case(gateway_records, bank_records, ground_truth, "B-04", "1:1",
        [{"payment_id": "GTW-B04", "amount": "1000.00", "gross_amount": "1000.00", "fee": "20.00", "net_amount": "980.00", "currency": "INR", "created_at": "2025-01-15", "merchant_txn_ref": "PAY-B04"}],
        [{"bank_reference": "BANK-B04", "settlement_amount": "980.00", "currency": "INR", "posting_date": "2025-01-17", "narration": "PAY-B04", "fee": "20.00"}],
        "MATCHED", "FEE_DEDUCTION", reconciled_amount="1000.00"
    )

    # B-05 Settlement — 0 days
    add_case(gateway_records, bank_records, ground_truth, "B-05", "1:1",
        [{"payment_id": "GTW-B05", "amount": "1000.00", "currency": "INR", "created_at": "2025-01-15", "merchant_txn_ref": "PAY-B05"}],
        [{"bank_reference": "BANK-B05", "settlement_amount": "1000.00", "currency": "INR", "posting_date": "2025-01-15", "narration": "PAY-B05"}],
        "MATCHED", reconciled_amount="1000.00"
    )

    # B-06 Settlement — 2 days
    add_case(gateway_records, bank_records, ground_truth, "B-06", "1:1",
        [{"payment_id": "GTW-B06", "amount": "1000.00", "currency": "INR", "created_at": "2025-01-15", "merchant_txn_ref": "PAY-B06"}],
        [{"bank_reference": "BANK-B06", "settlement_amount": "1000.00", "currency": "INR", "posting_date": "2025-01-17", "narration": "PAY-B06"}],
        "MATCHED", reconciled_amount="1000.00"
    )

    # B-07 Settlement — 5 days
    add_case(gateway_records, bank_records, ground_truth, "B-07", "1:1",
        [{"payment_id": "GTW-B07", "amount": "1000.00", "currency": "INR", "created_at": "2025-01-15", "merchant_txn_ref": "PAY-B07"}],
        [{"bank_reference": "BANK-B07", "settlement_amount": "1000.00", "currency": "INR", "posting_date": "2025-01-20", "narration": "PAY-B07"}],
        "MATCHED", "SETTLEMENT_DELAY", reconciled_amount="1000.00"
    )

    # B-08 Settlement — 10 days
    add_case(gateway_records, bank_records, ground_truth, "B-08", "1:1",
        [{"payment_id": "GTW-B08", "amount": "12000.00", "currency": "INR", "created_at": "2025-01-10", "merchant_txn_ref": "PAY-B08"}],
        [{"bank_reference": "BANK-B08", "settlement_amount": "12000.00", "currency": "INR", "posting_date": "2025-01-20", "narration": "PAY-B08"}],
        "MATCHED", "SETTLEMENT_DELAY", reconciled_amount="12000.00", notes="10-day delay; HIGH severity; flag_for_review=true"
    )

    # C-01 1:N split — 2 bank entries
    add_case(gateway_records, bank_records, ground_truth, "C-01", "1:N",
        [{"payment_id": "GTW-C01", "amount": "10000.00", "currency": "INR", "created_at": "2025-02-01"}],
        [
            {"bank_reference": "BANK-C01-1", "settlement_amount": "6000.00", "currency": "INR", "posting_date": "2025-02-03"},
            {"bank_reference": "BANK-C01-2", "settlement_amount": "4000.00", "currency": "INR", "posting_date": "2025-02-03"}
        ],
        "MATCHED", reconciled_amount="10000.00"
    )

    # C-02 1:N split — 3 bank entries
    add_case(gateway_records, bank_records, ground_truth, "C-02", "1:N",
        [{"payment_id": "GTW-C02", "amount": "10000.00", "currency": "INR", "created_at": "2025-02-01"}],
        [
            {"bank_reference": "BANK-C02-1", "settlement_amount": "5000.00", "currency": "INR", "posting_date": "2025-02-03"},
            {"bank_reference": "BANK-C02-2", "settlement_amount": "3000.00", "currency": "INR", "posting_date": "2025-02-03"},
            {"bank_reference": "BANK-C02-3", "settlement_amount": "2000.00", "currency": "INR", "posting_date": "2025-02-03"}
        ],
        "MATCHED", reconciled_amount="10000.00"
    )

    # C-03 N:1 batch — 2 gateway txns
    add_case(gateway_records, bank_records, ground_truth, "C-03", "N:1",
        [
            {"payment_id": "GTW-C03-1", "amount": "3000.00", "currency": "INR", "created_at": "2025-02-10"},
            {"payment_id": "GTW-C03-2", "amount": "7000.00", "currency": "INR", "created_at": "2025-02-10"}
        ],
        [{"bank_reference": "BANK-C03", "settlement_amount": "10000.00", "currency": "INR", "posting_date": "2025-02-12"}],
        "MATCHED", reconciled_amount="10000.00"
    )

    # C-04 N:1 batch — 3 gateway txns
    add_case(gateway_records, bank_records, ground_truth, "C-04", "N:1",
        [
            {"payment_id": "GTW-C04-1", "amount": "2000.00", "currency": "INR", "created_at": "2025-02-10"},
            {"payment_id": "GTW-C04-2", "amount": "3000.00", "currency": "INR", "created_at": "2025-02-10"},
            {"payment_id": "GTW-C04-3", "amount": "5000.00", "currency": "INR", "created_at": "2025-02-10"}
        ],
        [{"bank_reference": "BANK-C04", "settlement_amount": "10000.00", "currency": "INR", "posting_date": "2025-02-12"}],
        "MATCHED", reconciled_amount="10000.00"
    )

    # C-05 1:N with rounding in one component
    add_case(gateway_records, bank_records, ground_truth, "C-05", "1:N",
        [{"payment_id": "GTW-C05", "amount": "10000.00", "currency": "INR", "created_at": "2025-02-01"}],
        [
            {"bank_reference": "BANK-C05-1", "settlement_amount": "6000.00", "currency": "INR", "posting_date": "2025-02-03"},
            {"bank_reference": "BANK-C05-2", "settlement_amount": "3999.00", "currency": "INR", "posting_date": "2025-02-03"}
        ],
        "MATCHED", "ROUNDING_DIFFERENCE", reconciled_amount="10000.00"
    )

    # C-06 N:1 with fee deduction
    add_case(gateway_records, bank_records, ground_truth, "C-06", "N:1",
        [
            {"payment_id": "GTW-C06-1", "amount": "3000.00", "currency": "INR", "created_at": "2025-02-10"},
            {"payment_id": "GTW-C06-2", "amount": "7000.00", "currency": "INR", "created_at": "2025-02-10"}
        ],
        [{"bank_reference": "BANK-C06", "settlement_amount": "9998.50", "currency": "INR", "posting_date": "2025-02-12"}],
        "MATCHED", "FEE_DEDUCTION", reconciled_amount="10000.00"
    )

    # D-01 Orphan gateway — no bank match
    add_case(gateway_records, bank_records, ground_truth, "D-01", "1:1",
        [{"payment_id": "GTW-D01", "amount": "8500.00", "currency": "INR", "created_at": "2025-03-01"}],
        [],
        "EXCEPTION", "MISSING_RECORD", reconciled_amount="0.00"
    )

    # D-02 Orphan gateway — recent transaction
    add_case(gateway_records, bank_records, ground_truth, "D-02", "1:1",
        [{"payment_id": "GTW-D02", "amount": "8500.00", "currency": "INR", "created_at": "2025-10-01"}],
        [],
        "EXCEPTION", "MISSING_RECORD", reconciled_amount="0.00"
    )

    # D-03 Orphan bank — no gateway match
    # A genuine orphan with no gateway equivalent
    add_case(gateway_records, bank_records, ground_truth, "D-03", "1:1",
        [],
        [{"bank_reference": "BANK-ORPH-001", "settlement_amount": "2200.00", "currency": "INR", "posting_date": "2025-03-05", "narration": "ORPHAN-ENTRY"}],
        "EXCEPTION", "MISSING_RECORD", reconciled_amount="0.00"
    )

    # D-04 Orphan bank — small amount
    add_case(gateway_records, bank_records, ground_truth, "D-04", "1:1",
        [],
        [{"bank_reference": "BANK-D04", "settlement_amount": "15.00", "currency": "INR", "posting_date": "2025-03-05"}],
        "EXCEPTION", "MISSING_RECORD", reconciled_amount="0.00"
    )

    # D-05 Currency mismatch
    add_case(gateway_records, bank_records, ground_truth, "D-05", "1:1",
        [{"payment_id": "GTW-D05", "amount": "1000.00", "currency": "INR", "created_at": "2025-03-01", "merchant_txn_ref": "PAY-D05"}],
        [{"bank_reference": "BANK-D05", "settlement_amount": "1000.00", "currency": "USD", "posting_date": "2025-03-03", "narration": "PAY-D05"}],
        "EXCEPTION", "CURRENCY_MISMATCH", reconciled_amount="1000.00"
    )

    # D-06 Partial settlement
    add_case(gateway_records, bank_records, ground_truth, "D-06", "1:1",
        [{"payment_id": "GTW-D06", "amount": "10000.00", "currency": "INR", "created_at": "2025-03-01", "merchant_txn_ref": "PAY-D06"}],
        [{"bank_reference": "BANK-D06", "settlement_amount": "6000.00", "currency": "INR", "posting_date": "2025-03-03", "narration": "PAY-D06"}],
        "EXCEPTION", "PARTIAL_SETTLEMENT", reconciled_amount="10000.00"
    )

    # D-07 Deterministic duplicate
    add_case(gateway_records, bank_records, ground_truth, "D-07", "1:1",
        [{"payment_id": "GTW-D07", "amount": "5000.00", "currency": "INR", "created_at": "2025-01-15", "merchant_txn_ref": "PAY-10001"}], # exact same content as A-01 (excluding ID)
        [],
        "EXCEPTION", "DUPLICATE", reconciled_amount="5000.00"
    )

    # D-08 Possible duplicate — AI suspicion
    add_case(gateway_records, bank_records, ground_truth, "D-08", "1:1",
        [{"payment_id": "GTW-D08", "amount": "5000.00", "currency": "INR", "created_at": "2025-01-16", "merchant_txn_ref": "PAY-10001-B"}], # similar to A-01
        [],
        "EXCEPTION", "POSSIBLE_DUPLICATE", reconciled_amount="5000.00"
    )

    # D-09 Unknown / ambiguous
    add_case(gateway_records, bank_records, ground_truth, "D-09", "1:1",
        [{"payment_id": "GTW-D09", "amount": "1000.00", "currency": "INR", "created_at": "2025-03-01", "merchant_txn_ref": "PAY-D09"}],
        [{"bank_reference": "BANK-D09", "settlement_amount": "1200.00", "currency": "INR", "posting_date": "2025-03-03", "narration": "PAY-D09"}],
        "EXCEPTION", "UNKNOWN", reconciled_amount="1000.00"
    )

    # E-01 Adversarial split — irregular sub-amounts
    add_case(gateway_records, bank_records, ground_truth, "E-01", "1:N",
        [{"payment_id": "GTW-E01", "amount": "15000.00", "currency": "INR", "created_at": "2025-02-01"}],
        [
            {"bank_reference": "BANK-E01-1", "settlement_amount": "9237.00", "currency": "INR", "posting_date": "2025-02-03"},
            {"bank_reference": "BANK-E01-2", "settlement_amount": "5763.00", "currency": "INR", "posting_date": "2025-02-03"}
        ],
        "MATCHED", reconciled_amount="15000.00"
    )

    # E-02a Near-miss pair — transaction A
    add_case(gateway_records, bank_records, ground_truth, "E-02a", "1:1",
        [{"payment_id": "GTW-E02a", "amount": "10000.00", "currency": "INR", "created_at": "2025-01-15"}],
        [{"bank_reference": "BANK-E02a", "settlement_amount": "10000.00", "currency": "INR", "posting_date": "2025-01-17"}],
        "MATCHED", reconciled_amount="10000.00"
    )

    # E-02b Near-miss pair — transaction B
    add_case(gateway_records, bank_records, ground_truth, "E-02b", "1:1",
        [{"payment_id": "GTW-E02b", "amount": "10001.00", "currency": "INR", "created_at": "2025-01-15"}],
        [{"bank_reference": "BANK-E02b", "settlement_amount": "10001.00", "currency": "INR", "posting_date": "2025-01-18"}],
        "MATCHED", reconciled_amount="10001.00"
    )

    # E-03 Ambiguous candidate pool
    add_case(gateway_records, bank_records, ground_truth, "E-03", "1:1",
        [{"payment_id": "GTW-E03", "amount": "5000.00", "currency": "INR", "created_at": "2025-01-15", "merchant_txn_ref": "PAY-E03-GTW"}],
        [{"bank_reference": "BANK-E03", "settlement_amount": "5000.00", "currency": "INR", "posting_date": "2025-01-17", "narration": "BANK-E03-TRG"}],
        "MATCHED", reconciled_amount="5000.00"
    )
    # The decoy for E-03 is explicitly added to the bank dataset, without being part of any ground truth relation.
    bank_records.append({
        "bank_reference": "BANK-D03",
        "settlement_amount": "5000.00",
        "currency": "INR",
        "posting_date": "2025-01-18",
        "narration": "BANK-D03-DEC"
    })

    # E-04 Invalid settlement chronology
    add_case(gateway_records, bank_records, ground_truth, "E-04", "1:1",
        [{"payment_id": "GTW-E04", "amount": "1000.00", "currency": "INR", "created_at": "2025-03-10", "merchant_txn_ref": "PAY-E04"}],
        [{"bank_reference": "BANK-E04", "settlement_amount": "1000.00", "currency": "INR", "posting_date": "2025-03-08", "narration": "PAY-E04"}],
        "EXCEPTION", None, reconciled_amount="1000.00", notes="Validation exception: settlement_date precedes transaction_date."
    )

    # E-05 Amount difference outside all tolerances
    add_case(gateway_records, bank_records, ground_truth, "E-05", "1:1",
        [{"payment_id": "GTW-E05", "amount": "1000.00", "currency": "INR", "created_at": "2025-03-10", "merchant_txn_ref": "PAY-E05"}],
        [{"bank_reference": "BANK-E05", "settlement_amount": "1200.00", "currency": "INR", "posting_date": "2025-03-12", "narration": "PAY-E05"}],
        "EXCEPTION", "UNKNOWN", reconciled_amount="1000.00"
    )

    # E-06 Problematic split settlement — aggregate shortfall
    add_case(gateway_records, bank_records, ground_truth, "E-06", "1:N",
        [{"payment_id": "GTW-E06", "amount": "10000.00", "currency": "INR", "created_at": "2025-03-10"}],
        [
            {"bank_reference": "BANK-E06-1", "settlement_amount": "6000.00", "currency": "INR", "posting_date": "2025-03-12"},
            {"bank_reference": "BANK-E06-2", "settlement_amount": "2500.00", "currency": "INR", "posting_date": "2025-03-13"}
        ],
        "EXCEPTION", "SPLIT_SETTLEMENT", reconciled_amount="10000.00"
    )

    os.makedirs("data/synthetic", exist_ok=True)
    
    # Get all fields for CSV headers
    gateway_fields = set()
    for row in gateway_records:
        gateway_fields.update(row.keys())
    gateway_fields = ["payment_id", "merchant_txn_ref", "amount", "currency", "created_at", "merchant_name", "gross_amount", "fee", "net_amount"] # Order them nicely
    gateway_fields = [f for f in gateway_fields if any(f in r for r in gateway_records)]
    
    with open("data/synthetic/gateway.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=gateway_fields)
        writer.writeheader()
        writer.writerows(gateway_records)

    bank_fields = set()
    for row in bank_records:
        bank_fields.update(row.keys())
    bank_fields = ["bank_reference", "narration", "settlement_amount", "currency", "posting_date", "counterparty", "fee"]
    bank_fields = [f for f in bank_fields if any(f in r for r in bank_records)]

    with open("data/synthetic/bank.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=bank_fields)
        writer.writeheader()
        writer.writerows(bank_records)

    with open("data/synthetic/ground_truth.json", "w") as f:
        json.dump({"relationships": ground_truth}, f, indent=2)

if __name__ == "__main__":
    generate_dataset()
