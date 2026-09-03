"""CSV extractor for ingesting transaction records into CanonicalRecords."""

import csv
import io
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import BinaryIO, List, TextIO, Union

from eagle.models.canonical import CanonicalRecord


class ExtractionValidationError(ValueError):
    """Raised when CSV or JSON data fails validation or parsing."""
    pass


class CsvExtractor:
    """Extracts and validates CanonicalRecord instances from CSV data."""

    def extract(
        self,
        source_input: Union[str, Path, TextIO, BinaryIO, bytes],
        source_type: str = "AUTO",
    ) -> List[CanonicalRecord]:
        """Extract canonical records from a CSV file, string, or stream.

        Args:
            source_input: Path, string content, bytes, or file-like object.
            source_type: "GATEWAY", "BANK", "CANONICAL", or "AUTO" (inferred from headers).

        Returns:
            List of validated CanonicalRecord objects.

        Raises:
            ExtractionValidationError: If input is empty, malformed, or contains invalid/duplicate records.
        """
        text_content = self._read_text(source_input)
        if not text_content or not text_content.strip():
            raise ExtractionValidationError("CSV input is empty.")

        try:
            reader = csv.DictReader(io.StringIO(text_content.strip()))
        except Exception as e:
            raise ExtractionValidationError(f"Malformed CSV input: {e}") from e

        if not reader.fieldnames:
            raise ExtractionValidationError("CSV contains no headers or field names.")

        fieldnames = [f.strip().lower() for f in reader.fieldnames if f]
        detected_type = self._detect_source_type(fieldnames, source_type)

        records: List[CanonicalRecord] = []
        seen_record_ids: set[str] = set()

        for row_idx, raw_row in enumerate(reader, start=1):
            # Normalize dictionary keys to lowercase and stripped values
            row = {k.strip().lower(): v.strip() for k, v in raw_row.items() if k is not None and v is not None}
            if not any(row.values()):
                # Skip empty lines
                continue

            record = self._parse_row(row, detected_type, row_idx)
            if record.record_id in seen_record_ids:
                raise ExtractionValidationError(
                    f"Duplicate record ID '{record.record_id}' found at row {row_idx}."
                )
            seen_record_ids.add(record.record_id)
            records.append(record)

        if not records:
            raise ExtractionValidationError("CSV contains no valid transaction rows.")

        return records

    def _read_text(self, source_input: Union[str, Path, TextIO, BinaryIO, bytes]) -> str:
        """Convert various input types to a unified string."""
        if isinstance(source_input, Path):
            if not source_input.exists():
                raise ExtractionValidationError(f"File does not exist: {source_input}")
            return source_input.read_text(encoding="utf-8")
        elif isinstance(source_input, str):
            # Check if it's a file path on disk
            try:
                p = Path(source_input)
                if p.is_file():
                    return p.read_text(encoding="utf-8")
            except (OSError, ValueError):
                pass
            return source_input
        elif isinstance(source_input, bytes):
            return source_input.decode("utf-8")
        elif hasattr(source_input, "read"):
            content = source_input.read()
            if isinstance(content, bytes):
                return content.decode("utf-8")
            return str(content)
        else:
            raise ExtractionValidationError(f"Unsupported input type: {type(source_input)}")

    def _detect_source_type(self, fieldnames: List[str], requested_type: str) -> str:
        """Determine whether the CSV is GATEWAY, BANK, or generic CANONICAL."""
        req = requested_type.upper().strip()
        if req in ("GATEWAY", "BANK", "CANONICAL"):
            return req

        # Automatic detection by header signature
        if "payment_id" in fieldnames:
            return "GATEWAY"
        elif "bank_reference" in fieldnames or "settlement_amount" in fieldnames:
            return "BANK"
        elif "record_id" in fieldnames and "source_reference" in fieldnames:
            return "CANONICAL"
        else:
            # Check for generic amount and date fields
            if "amount" in fieldnames and ("date" in fieldnames or "transaction_date" in fieldnames):
                return "CANONICAL"
            raise ExtractionValidationError(
                f"Cannot automatically detect CSV schema from headers: {fieldnames}. "
                "Expected Gateway ('payment_id'), Bank ('bank_reference'), or Canonical ('record_id') columns."
            )

    def _parse_row(self, row: dict, source_type: str, row_idx: int) -> CanonicalRecord:
        """Parse a normalized row dictionary into a CanonicalRecord."""
        try:
            if source_type == "GATEWAY":
                return self._parse_gateway_row(row, row_idx)
            elif source_type == "BANK":
                return self._parse_bank_row(row, row_idx)
            else:
                return self._parse_canonical_row(row, row_idx)
        except ExtractionValidationError:
            raise
        except Exception as e:
            raise ExtractionValidationError(f"Failed to parse row {row_idx}: {e}") from e

    def _parse_gateway_row(self, row: dict, row_idx: int) -> CanonicalRecord:
        """Map synthetic/production Gateway CSV columns to CanonicalRecord."""
        record_id = self._get_required(row, ["payment_id", "record_id", "transaction_id"], row_idx)
        reference = (
            row.get("merchant_txn_ref")
            or row.get("source_reference")
            or row.get("reference")
            or row.get("ref")
            or row.get("txn_ref")
            or row.get("external_ref")
            or ""
        )
        amount = self._parse_decimal(self._get_required(row, ["amount"], row_idx), "amount", row_idx)
        currency = (row.get("currency") or "INR").upper().strip()
        
        date_str = self._get_required(row, ["created_at", "transaction_date", "date"], row_idx)
        txn_date = self._parse_date(date_str, "created_at", row_idx)
        settle_date = txn_date

        counterparty = row.get("merchant_name") or row.get("counterparty") or ""
        gross_amount = self._parse_optional_decimal(row.get("gross_amount"), "gross_amount", row_idx)
        fee_amount = self._parse_optional_decimal(row.get("fee") or row.get("fee_amount"), "fee", row_idx)
        net_amount = self._parse_optional_decimal(row.get("net_amount"), "net_amount", row_idx)

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

    def _parse_bank_row(self, row: dict, row_idx: int) -> CanonicalRecord:
        """Map synthetic/production Bank CSV columns to CanonicalRecord."""
        record_id = self._get_required(row, ["bank_reference", "record_id", "transaction_id"], row_idx)
        reference = (
            row.get("narration")
            or row.get("source_reference")
            or row.get("reference")
            or row.get("ref")
            or row.get("txn_ref")
            or ""
        )
        amount_str = self._get_required(row, ["settlement_amount", "amount"], row_idx)
        amount = self._parse_decimal(amount_str, "settlement_amount", row_idx)
        currency = (row.get("currency") or "INR").upper().strip()

        date_str = self._get_required(row, ["posting_date", "settlement_date", "date"], row_idx)
        settle_date = self._parse_date(date_str, "posting_date", row_idx)
        txn_date = settle_date

        counterparty = row.get("counterparty") or row.get("merchant_name") or ""
        fee_amount = self._parse_optional_decimal(row.get("fee") or row.get("fee_amount"), "fee", row_idx)
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

    def _parse_canonical_row(self, row: dict, row_idx: int) -> CanonicalRecord:
        """Map standard canonical fields directly to CanonicalRecord."""
        record_id = self._get_required(row, ["record_id", "transaction_id"], row_idx)
        transaction_id = row.get("transaction_id") or record_id
        source = (row.get("source") or "MANUAL").upper().strip()
        source_reference = (
            row.get("source_reference")
            or row.get("reference")
            or row.get("merchant_txn_ref")
            or row.get("narration")
            or row.get("ref")
            or row.get("txn_ref")
            or ""
        )
        amount = self._parse_decimal(self._get_required(row, ["amount"], row_idx), "amount", row_idx)
        currency = (row.get("currency") or "INR").upper().strip()

        txn_date_str = self._get_required(row, ["transaction_date", "date", "created_at"], row_idx)
        txn_date = self._parse_date(txn_date_str, "transaction_date", row_idx)
        settle_date_str = row.get("settlement_date") or row.get("posting_date") or txn_date_str
        settle_date = self._parse_date(settle_date_str, "settlement_date", row_idx)

        counterparty = row.get("counterparty") or row.get("merchant_name") or ""
        status = (row.get("status") or "COMPLETED").upper().strip()
        transaction_type = (row.get("transaction_type") or "PAYMENT").upper().strip()

        gross_amount = self._parse_optional_decimal(row.get("gross_amount"), "gross_amount", row_idx)
        fee_amount = self._parse_optional_decimal(row.get("fee_amount") or row.get("fee"), "fee_amount", row_idx)
        net_amount = self._parse_optional_decimal(row.get("net_amount"), "net_amount", row_idx)

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

    def _get_required(self, row: dict, candidate_keys: List[str], row_idx: int) -> str:
        """Retrieve the first matching non-empty required field."""
        for key in candidate_keys:
            val = row.get(key)
            if val is not None and str(val).strip():
                return str(val).strip()
        raise ExtractionValidationError(
            f"Missing required field (expected one of {candidate_keys}) at row {row_idx}."
        )

    def _parse_decimal(self, val_str: str, field_name: str, row_idx: int) -> Decimal:
        """Parse string to Decimal with clean validation."""
        cleaned = val_str.replace(",", "").strip()
        try:
            return Decimal(cleaned)
        except (InvalidOperation, TypeError, ValueError) as e:
            raise ExtractionValidationError(
                f"Invalid Decimal amount '{val_str}' for field '{field_name}' at row {row_idx}."
            ) from e

    def _parse_optional_decimal(self, val: any, field_name: str, row_idx: int) -> Decimal | None:
        """Parse optional Decimal field."""
        if val is None:
            return None
        s = str(val).strip()
        if not s:
            return None
        return self._parse_decimal(s, field_name, row_idx)

    def _parse_date(self, val_str: str, field_name: str, row_idx: int) -> date:
        """Parse date string supporting multiple common formats."""
        cleaned = val_str.strip()
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
                return datetime.strptime(cleaned, fmt).date()
            except ValueError:
                continue

        # Try ISO format
        try:
            return date.fromisoformat(cleaned)
        except ValueError:
            pass

        raise ExtractionValidationError(
            f"Invalid date '{val_str}' for field '{field_name}' at row {row_idx}. "
            "Expected format YYYY-MM-DD."
        )


def extract_csv(
    source_input: Union[str, Path, TextIO, BinaryIO, bytes],
    source_type: str = "AUTO",
) -> List[CanonicalRecord]:
    """Convenience function to extract CanonicalRecords from CSV."""
    return CsvExtractor().extract(source_input, source_type)
