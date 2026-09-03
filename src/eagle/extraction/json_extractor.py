"""JSON extractor for ingesting transaction records into CanonicalRecords."""

import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import BinaryIO, List, TextIO, Union

from eagle.extraction.csv_extractor import ExtractionValidationError
from eagle.models.canonical import CanonicalRecord


class JsonExtractor:
    """Extracts and validates CanonicalRecord instances from JSON data."""

    def extract(
        self,
        source_input: Union[str, Path, TextIO, BinaryIO, bytes, list, dict],
        source_type: str = "AUTO",
    ) -> List[CanonicalRecord]:
        """Extract canonical records from a JSON file, string, stream, or Python data structure.

        Args:
            source_input: JSON string, Path, bytes, stream, list, or dict.
            source_type: "GATEWAY", "BANK", "CANONICAL", or "AUTO".

        Returns:
            List of validated CanonicalRecord objects.

        Raises:
            ExtractionValidationError: If input is empty, malformed, or contains invalid/duplicate records.
        """
        raw_data = self._load_data(source_input)
        
        # Normalize list from various wrapper formats
        items: List[dict] = []
        if isinstance(raw_data, list):
            items = raw_data
        elif isinstance(raw_data, dict):
            if "records" in raw_data and isinstance(raw_data["records"], list):
                items = raw_data["records"]
            elif "data" in raw_data and isinstance(raw_data["data"], list):
                items = raw_data["data"]
            elif "transactions" in raw_data and isinstance(raw_data["transactions"], list):
                items = raw_data["transactions"]
            else:
                # Assume single record object
                items = [raw_data]
        else:
            raise ExtractionValidationError(
                f"Expected JSON list or object with records array, got {type(raw_data).__name__}."
            )

        if not items:
            raise ExtractionValidationError("JSON input contains no records.")

        records: List[CanonicalRecord] = []
        seen_record_ids: set[str] = set()

        for idx, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                raise ExtractionValidationError(
                    f"Record at index {idx} is not a JSON object: {type(item).__name__}."
                )
            
            # Normalize keys to lowercase string
            row = {str(k).strip().lower(): v for k, v in item.items() if k is not None}
            record = self._parse_json_record(row, source_type, idx)

            if record.record_id in seen_record_ids:
                raise ExtractionValidationError(
                    f"Duplicate record ID '{record.record_id}' found at index {idx}."
                )
            seen_record_ids.add(record.record_id)
            records.append(record)

        return records

    def _load_data(self, source_input: Union[str, Path, TextIO, BinaryIO, bytes, list, dict]) -> any:
        """Parse raw input into Python data structure."""
        if isinstance(source_input, (list, dict)):
            return source_input

        text = ""
        if isinstance(source_input, Path):
            if not source_input.exists():
                raise ExtractionValidationError(f"File does not exist: {source_input}")
            text = source_input.read_text(encoding="utf-8")
        elif isinstance(source_input, str):
            # Check if it's a file path
            try:
                p = Path(source_input)
                if p.is_file():
                    text = p.read_text(encoding="utf-8")
                else:
                    text = source_input
            except (OSError, ValueError):
                text = source_input
        elif isinstance(source_input, bytes):
            text = source_input.decode("utf-8")
        elif hasattr(source_input, "read"):
            content = source_input.read()
            text = content.decode("utf-8") if isinstance(content, bytes) else str(content)
        else:
            raise ExtractionValidationError(f"Unsupported input type: {type(source_input)}")

        if not text or not text.strip():
            raise ExtractionValidationError("JSON input is empty.")

        try:
            return json.loads(text.strip())
        except Exception as e:
            raise ExtractionValidationError(f"Malformed JSON input: {e}") from e

    def _parse_json_record(self, row: dict, source_type: str, idx: int) -> CanonicalRecord:
        """Parse dictionary item into CanonicalRecord with type validation."""
        try:
            # Detect source type if AUTO
            effective_type = source_type.upper().strip()
            if effective_type == "AUTO":
                if "payment_id" in row:
                    effective_type = "GATEWAY"
                elif "bank_reference" in row or "settlement_amount" in row:
                    effective_type = "BANK"
                else:
                    effective_type = "CANONICAL"

            if effective_type == "GATEWAY":
                record_id = self._get_required(row, ["payment_id", "record_id", "transaction_id"], idx)
                reference = str(
                    row.get("merchant_txn_ref")
                    or row.get("source_reference")
                    or row.get("reference")
                    or row.get("ref")
                    or row.get("txn_ref")
                    or row.get("external_ref")
                    or ""
                )
                amount = self._parse_decimal(self._get_required(row, ["amount"], idx), "amount", idx)
                currency = str(row.get("currency") or "INR").upper().strip()
                
                date_val = self._get_required(row, ["created_at", "transaction_date", "date"], idx)
                txn_date = self._parse_date(date_val, "created_at", idx)
                settle_date = txn_date

                counterparty = str(row.get("merchant_name") or row.get("counterparty") or "")
                gross_amount = self._parse_optional_decimal(row.get("gross_amount"), "gross_amount", idx)
                fee_amount = self._parse_optional_decimal(row.get("fee") or row.get("fee_amount"), "fee", idx)
                net_amount = self._parse_optional_decimal(row.get("net_amount"), "net_amount", idx)

                return CanonicalRecord(
                    record_id=record_id,
                    transaction_id=record_id,
                    source="GATEWAY",
                    source_reference=reference,
                    amount=amount,
                    currency=currency,
                    transaction_date=txn_date,
                    settlement_date=settle_date,
                    counterparty=counterparty,
                    status="COMPLETED",
                    transaction_type="PAYMENT",
                    gross_amount=gross_amount,
                    fee_amount=fee_amount,
                    net_amount=net_amount,
                )

            elif effective_type == "BANK":
                record_id = self._get_required(row, ["bank_reference", "record_id", "transaction_id"], idx)
                reference = str(
                    row.get("narration")
                    or row.get("source_reference")
                    or row.get("reference")
                    or row.get("ref")
                    or row.get("txn_ref")
                    or ""
                )
                amount_val = self._get_required(row, ["settlement_amount", "amount"], idx)
                amount = self._parse_decimal(amount_val, "settlement_amount", idx)
                currency = str(row.get("currency") or "INR").upper().strip()

                date_val = self._get_required(row, ["posting_date", "settlement_date", "date"], idx)
                settle_date = self._parse_date(date_val, "posting_date", idx)
                txn_date = settle_date

                counterparty = str(row.get("counterparty") or row.get("merchant_name") or "")
                fee_amount = self._parse_optional_decimal(row.get("fee") or row.get("fee_amount"), "fee", idx)
                txn_type = "CREDIT" if amount >= Decimal("0.00") else "DEBIT"

                return CanonicalRecord(
                    record_id=record_id,
                    transaction_id=record_id,
                    source="BANK",
                    source_reference=reference,
                    amount=amount,
                    currency=currency,
                    transaction_date=txn_date,
                    settlement_date=settle_date,
                    counterparty=counterparty,
                    status="POSTED",
                    transaction_type=txn_type,
                    fee_amount=fee_amount,
                )

            else:
                record_id = self._get_required(row, ["record_id", "transaction_id"], idx)
                transaction_id = str(row.get("transaction_id") or record_id)
                source = str(row.get("source") or "MANUAL").upper().strip()
                source_reference = str(
                    row.get("source_reference")
                    or row.get("reference")
                    or row.get("merchant_txn_ref")
                    or row.get("narration")
                    or row.get("ref")
                    or row.get("txn_ref")
                    or ""
                )
                amount = self._parse_decimal(self._get_required(row, ["amount"], idx), "amount", idx)
                currency = str(row.get("currency") or "INR").upper().strip()

                txn_date_val = self._get_required(row, ["transaction_date", "date", "created_at"], idx)
                txn_date = self._parse_date(txn_date_val, "transaction_date", idx)
                settle_date_val = row.get("settlement_date") or row.get("posting_date") or txn_date_val
                settle_date = self._parse_date(settle_date_val, "settlement_date", idx)

                counterparty = str(row.get("counterparty") or row.get("merchant_name") or "")
                status = str(row.get("status") or "COMPLETED").upper().strip()
                transaction_type = str(row.get("transaction_type") or "PAYMENT").upper().strip()

                gross_amount = self._parse_optional_decimal(row.get("gross_amount"), "gross_amount", idx)
                fee_amount = self._parse_optional_decimal(row.get("fee_amount") or row.get("fee"), "fee_amount", idx)
                net_amount = self._parse_optional_decimal(row.get("net_amount"), "net_amount", idx)

                return CanonicalRecord(
                    record_id=record_id,
                    transaction_id=transaction_id,
                    source=source,
                    source_reference=source_reference,
                    amount=amount,
                    currency=currency,
                    transaction_date=txn_date,
                    settlement_date=settle_date,
                    counterparty=counterparty,
                    status=status,
                    transaction_type=transaction_type,
                    gross_amount=gross_amount,
                    fee_amount=fee_amount,
                    net_amount=net_amount,
                )

        except ExtractionValidationError:
            raise
        except Exception as e:
            raise ExtractionValidationError(f"Failed to parse JSON record at index {idx}: {e}") from e

    def _get_required(self, row: dict, candidate_keys: List[str], idx: int) -> any:
        """Retrieve first non-empty required field."""
        for key in candidate_keys:
            val = row.get(key)
            if val is not None and str(val).strip():
                return val
        raise ExtractionValidationError(
            f"Missing required field (expected one of {candidate_keys}) at index {idx}."
        )

    def _parse_decimal(self, val: any, field_name: str, idx: int) -> Decimal:
        """Parse value to Decimal."""
        if isinstance(val, Decimal):
            return val
        if isinstance(val, (int, float)):
            return Decimal(str(val))
        val_str = str(val).replace(",", "").strip()
        try:
            return Decimal(val_str)
        except (InvalidOperation, TypeError, ValueError) as e:
            raise ExtractionValidationError(
                f"Invalid Decimal amount '{val}' for field '{field_name}' at index {idx}."
            ) from e

    def _parse_optional_decimal(self, val: any, field_name: str, idx: int) -> Decimal | None:
        """Parse optional Decimal field."""
        if val is None or str(val).strip() == "":
            return None
        return self._parse_decimal(val, field_name, idx)

    def _parse_date(self, val: any, field_name: str, idx: int) -> date:
        """Parse value to date."""
        if isinstance(val, date) and not isinstance(val, datetime):
            return val
        if isinstance(val, datetime):
            return val.date()

        val_str = str(val).strip()
        date_formats = [
            "%Y-%m-%d",
            "%Y-%m-%d %H:%M:%S",
            "%Y/%m/%d",
            "%d-%m-%Y",
            "%d/%m/%Y",
            "%m/%d/%Y",
        ]
        for fmt in date_formats:
            try:
                return datetime.strptime(val_str, fmt).date()
            except ValueError:
                continue

        try:
            return date.fromisoformat(val_str)
        except ValueError:
            pass

        raise ExtractionValidationError(
            f"Invalid date '{val}' for field '{field_name}' at index {idx}. Expected YYYY-MM-DD."
        )


def extract_json(
    source_input: Union[str, Path, TextIO, BinaryIO, bytes, list, dict],
    source_type: str = "AUTO",
) -> List[CanonicalRecord]:
    """Convenience function to extract CanonicalRecords from JSON."""
    return JsonExtractor().extract(source_input, source_type)
