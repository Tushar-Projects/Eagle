"""Data loading utilities for evaluation."""

import csv
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from eagle.models.canonical import CanonicalRecord
from eagle.models.ground_truth import GroundTruthDataset


def load_gateway_records(csv_path: str) -> list[CanonicalRecord]:
    """Load canonical records from the synthetic gateway CSV."""
    records = []
    with open(csv_path, "r", encoding="utf-8") as f:
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


def load_bank_records(csv_path: str) -> list[CanonicalRecord]:
    """Load canonical records from the synthetic bank CSV."""
    records = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append(
                CanonicalRecord(
                    record_id=row["bank_reference"],
                    transaction_id=row["bank_reference"],
                    source="BANK",
                    source_reference=row["narration"],
                    amount=Decimal(row["settlement_amount"]),
                    currency=row["currency"],
                    transaction_date=datetime.strptime(row["posting_date"], "%Y-%m-%d").date(),
                    settlement_date=datetime.strptime(row["posting_date"], "%Y-%m-%d").date(),
                    counterparty=row.get("counterparty", ""),
                    status="POSTED",
                    transaction_type="CREDIT",
                    fee_amount=Decimal(row["fee"]) if row.get("fee") else None,
                )
            )
    return records


def load_ground_truth(json_path: str) -> GroundTruthDataset:
    """Load and validate the synthetic ground-truth dataset."""
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    return GroundTruthDataset.model_validate(data)
