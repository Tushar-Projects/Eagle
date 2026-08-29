"""Unit and integration tests for CSV and JSON data extraction."""

import io
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from eagle.extraction.csv_extractor import CsvExtractor, ExtractionValidationError, extract_csv
from eagle.extraction.json_extractor import JsonExtractor, extract_json
from eagle.models.canonical import CanonicalRecord


class TestCsvExtractor:
    """Test suite for CsvExtractor."""

    def test_valid_gateway_csv(self):
        csv_data = """payment_id,merchant_txn_ref,amount,currency,created_at,merchant_name,gross_amount,fee,net_amount
GTW-001,REF-100,5000.00,INR,2025-01-15,Acme Corp,5100.00,100.00,5000.00
GTW-002,REF-200,1500.50,INR,2025-01-16,Globex,,,
"""
        records = extract_csv(csv_data, source_type="GATEWAY")
        assert len(records) == 2
        assert records[0].record_id == "GTW-001"
        assert records[0].source == "GATEWAY"
        assert records[0].amount == Decimal("5000.00")
        assert records[0].currency == "INR"
        assert records[0].transaction_date == date(2025, 1, 15)
        assert records[0].gross_amount == Decimal("5100.00")
        assert records[0].fee_amount == Decimal("100.00")
        assert records[0].net_amount == Decimal("5000.00")
        assert records[0].counterparty == "Acme Corp"

        assert records[1].record_id == "GTW-002"
        assert records[1].amount == Decimal("1500.50")
        assert records[1].gross_amount is None

    def test_valid_bank_csv(self):
        csv_data = """bank_reference,narration,settlement_amount,currency,posting_date,counterparty,fee
BANK-001,REF-100,5000.00,INR,2025-01-17,Acme Corp,
BANK-002,REF-200,-1500.00,INR,2025-01-18,Globex,10.00
"""
        records = extract_csv(csv_data, source_type="BANK")
        assert len(records) == 2
        assert records[0].record_id == "BANK-001"
        assert records[0].source == "BANK"
        assert records[0].amount == Decimal("5000.00")
        assert records[0].transaction_type == "CREDIT"
        assert records[0].transaction_date == date(2025, 1, 17)

        assert records[1].record_id == "BANK-002"
        assert records[1].amount == Decimal("-1500.00")
        assert records[1].transaction_type == "DEBIT"
        assert records[1].fee_amount == Decimal("10.00")

    def test_auto_detection_of_source_type(self):
        gtw_csv = "payment_id,amount,created_at\nGTW-01,100.00,2025-01-01"
        bank_csv = "bank_reference,settlement_amount,posting_date\nBANK-01,100.00,2025-01-01"

        gtw_records = extract_csv(gtw_csv)
        assert gtw_records[0].source == "GATEWAY"

        bank_records = extract_csv(bank_csv)
        assert bank_records[0].source == "BANK"

    def test_empty_csv_raises_error(self):
        with pytest.raises(ExtractionValidationError, match="CSV input is empty"):
            extract_csv("")

        with pytest.raises(ExtractionValidationError, match="CSV contains no valid transaction rows"):
            extract_csv("payment_id,amount,created_at\n")

    def test_missing_required_field_raises_error(self):
        # Missing amount
        csv_data = "payment_id,created_at\nGTW-01,2025-01-01"
        with pytest.raises(ExtractionValidationError, match="Missing required field"):
            extract_csv(csv_data, source_type="GATEWAY")

    def test_invalid_decimal_amount_raises_error(self):
        csv_data = "payment_id,amount,created_at\nGTW-01,NOT_A_NUMBER,2025-01-01"
        with pytest.raises(ExtractionValidationError, match="Invalid Decimal amount"):
            extract_csv(csv_data, source_type="GATEWAY")

    def test_invalid_date_raises_error(self):
        csv_data = "payment_id,amount,created_at\nGTW-01,100.00,32-13-2025"
        with pytest.raises(ExtractionValidationError, match="Invalid date"):
            extract_csv(csv_data, source_type="GATEWAY")

    def test_duplicate_record_id_raises_error(self):
        csv_data = """payment_id,amount,created_at
GTW-01,100.00,2025-01-01
GTW-01,200.00,2025-01-02
"""
        with pytest.raises(ExtractionValidationError, match="Duplicate record ID 'GTW-01'"):
            extract_csv(csv_data, source_type="GATEWAY")

    def test_extract_from_synthetic_dataset_files(self):
        gtw_path = Path("data/synthetic/gateway.csv")
        bank_path = Path("data/synthetic/bank.csv")

        if gtw_path.exists() and bank_path.exists():
            gtw_records = extract_csv(gtw_path)
            bank_records = extract_csv(bank_path)

            assert len(gtw_records) == 40
            assert len(bank_records) == 41
            assert all(isinstance(r, CanonicalRecord) for r in gtw_records)
            assert all(isinstance(r, CanonicalRecord) for r in bank_records)


class TestJsonExtractor:
    """Test suite for JsonExtractor."""

    def test_valid_json_array_extraction(self):
        json_data = [
            {
                "payment_id": "GTW-101",
                "amount": "1250.75",
                "currency": "INR",
                "created_at": "2025-01-20",
                "merchant_name": "Test Merchant",
                "merchant_txn_ref": "REF-XYZ",
            },
            {
                "payment_id": "GTW-102",
                "amount": 500,
                "currency": "INR",
                "created_at": "2025-01-21",
            },
        ]
        records = extract_json(json_data, source_type="GATEWAY")
        assert len(records) == 2
        assert records[0].record_id == "GTW-101"
        assert records[0].amount == Decimal("1250.75")
        assert records[0].counterparty == "Test Merchant"
        assert records[1].amount == Decimal("500")

    def test_valid_json_wrapped_object(self):
        json_data = {
            "records": [
                {
                    "record_id": "REC-01",
                    "amount": "100.00",
                    "currency": "INR",
                    "transaction_date": "2025-01-01",
                    "source": "GATEWAY",
                }
            ]
        }
        records = extract_json(json_data)
        assert len(records) == 1
        assert records[0].record_id == "REC-01"

    def test_empty_json_raises_error(self):
        with pytest.raises(ExtractionValidationError, match="JSON input is empty"):
            extract_json("")

        with pytest.raises(ExtractionValidationError, match="JSON input contains no records"):
            extract_json("[]")

    def test_duplicate_json_record_id_raises_error(self):
        json_data = [
            {"payment_id": "GTW-01", "amount": "100.00", "created_at": "2025-01-01"},
            {"payment_id": "GTW-01", "amount": "200.00", "created_at": "2025-01-02"},
        ]
        with pytest.raises(ExtractionValidationError, match="Duplicate record ID 'GTW-01'"):
            extract_json(json_data, source_type="GATEWAY")

    def test_malformed_json_raises_error(self):
        with pytest.raises(ExtractionValidationError, match="Malformed JSON"):
            extract_json("{not_valid_json}")
