"""Deterministic normalization, filtering, and CanonicalRecord assembly utilities."""

import hashlib
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional, Tuple

from eagle.extraction.csv_extractor import ExtractionValidationError
from eagle.extraction.models import RawExtractedTransaction
from eagle.models.canonical import CanonicalRecord

# Currency symbol mapping to standard 3-letter ISO codes
CURRENCY_SYMBOL_MAP = {
    "₹": "INR",
    "RS.": "INR",
    "RS": "INR",
    "INR": "INR",
    "$": "USD",
    "USD": "USD",
    "€": "EUR",
    "EUR": "EUR",
    "£": "GBP",
    "GBP": "GBP",
    "¥": "JPY",
    "JPY": "JPY",
}

# Regex patterns for identifying non-transaction rows
NON_TRANSACTION_PATTERNS = [
    r"^\s*opening\s+balance",
    r"^\s*closing\s+balance",
    r"^\s*balance\s+b/?f",
    r"^\s*balance\s+c/?f",
    r"^\s*b/?f\s+balance",
    r"^\s*c/?f\s+balance",
    r"^\s*total",
    r"^\s*sub\s*total",
    r"^\s*grand\s*total",
    r"^\s*statement\s*total",
    r"^\s*page\s*total",
    r"^\s*daily\s*total",
    r"^\s*brought\s+forward",
    r"^\s*carried\s+forward",
    r"^\s*account\s+summary",
    r"^\s*transaction\s+details",
    r"^\s*page\s+\d+\s+of\s+\d+",
]

HEADER_KEYWORDS = {
    "date", "transaction", "txn", "posting", "value",
    "description", "narration", "particulars", "details",
    "amount", "withdrawal", "deposit", "debit", "credit", "balance",
    "ref", "reference", "chq", "no", "id", "payment", "merchant",
    "status", "currency", "type", "fee", "gross", "net",
}


def is_non_transaction_row(text: str) -> bool:
    """Check if row text matches obvious balance, summary, or header patterns."""
    if not text or not text.strip():
        return True

    cleaned = text.strip().lower()

    # 1. Check regex patterns for balance and total lines
    for pat in NON_TRANSACTION_PATTERNS:
        if re.search(pat, cleaned, re.IGNORECASE):
            return True

    # 2. Check if the line is purely column headers
    words = set(re.findall(r"\b[a-zA-Z_]+\b", cleaned))
    if words and words.issubset(HEADER_KEYWORDS):
        return True

    return False


def normalize_currency(raw_currency: Optional[str], amount_text: str = "") -> str:
    """Extract and normalize 3-letter ISO currency code."""
    if raw_currency:
        clean = raw_currency.strip().upper()
        if clean in CURRENCY_SYMBOL_MAP:
            return CURRENCY_SYMBOL_MAP[clean]
        if len(clean) == 3 and clean.isalpha():
            return clean

    # Check if currency symbol exists in amount text
    if amount_text:
        upper_amt = amount_text.upper()
        for sym, code in CURRENCY_SYMBOL_MAP.items():
            if sym in upper_amt:
                return code

    return "INR"  # Default canonical currency


def normalize_amount(raw_amount: str) -> Tuple[Decimal, Optional[str]]:
    """Parse monetary string into an exact Decimal and inferred transaction type (CREDIT/DEBIT).

    Handles:
    - INR notation: '₹ 1,25,000.50'
    - US/EU notation: '$1,500.00', '1.500,00'
    - Parentheses (accounting negative): '(450.00)' -> Decimal('-450.00')
    - Suffixes: '1000.00 CR' -> Decimal('1000.00'), CREDIT; '500.00 DR' -> Decimal('500.00'), DEBIT
    """
    if not raw_amount or not str(raw_amount).strip():
        raise ExtractionValidationError("Amount string is empty.")

    s = str(raw_amount).strip()

    # Detect CR / DR indicators
    inferred_type = None
    if re.search(r"\bCR\b", s, re.IGNORECASE) or s.endswith("+"):
        inferred_type = "CREDIT"
    elif re.search(r"\bDR\b", s, re.IGNORECASE) or s.endswith("-"):
        inferred_type = "DEBIT"

    # Detect accounting parentheses e.g. (1,200.50)
    is_parentheses = False
    paren_match = re.search(r"\(([^)]+)\)", s)
    if paren_match:
        is_parentheses = True
        s = paren_match.group(1)
        inferred_type = inferred_type or "DEBIT"

    # Strip currency symbols and letters
    cleaned = re.sub(r"[^\d.,\-+]", "", s).strip()

    if not cleaned:
        raise ExtractionValidationError(f"Could not extract numeric amount from '{raw_amount}'.")

    # Handle European decimal formatting (e.g. 1.234,50 -> 1234.50)
    if re.search(r"^\d{1,3}(\.\d{3})*,\d{2}$", cleaned):
        cleaned = cleaned.replace(".", "").replace(",", ".")
    else:
        # Standard format: remove commas (e.g. 1,25,000.50 -> 125000.50)
        cleaned = cleaned.replace(",", "")

    # Handle leading/trailing signs
    try:
        val = Decimal(cleaned)
    except (InvalidOperation, ValueError) as e:
        raise ExtractionValidationError(f"Invalid monetary Decimal amount: '{raw_amount}'") from e

    if is_parentheses and val > Decimal("0.00"):
        val = -val

    return val, inferred_type


def normalize_date(raw_date: str) -> date:
    """Parse date string into datetime.date supporting common international and Indian banking formats."""
    if not raw_date or not str(raw_date).strip():
        raise ExtractionValidationError("Date string is empty.")

    s = str(raw_date).strip()

    formats = [
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d.%m.%Y",
        "%d/%m/%y",
        "%d-%m-%y",
        "%d-%b-%Y",   # 15-Jan-2025
        "%d-%B-%Y",   # 15-January-2025
        "%d %b %Y",    # 15 Jan 2025
        "%d %B %Y",    # 15 January 2025
        "%b %d, %Y",   # Jan 15, 2025
        "%m/%d/%Y",    # US format
        "%Y/%m/%d",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue

    # ISO fallback
    try:
        return date.fromisoformat(s)
    except ValueError:
        pass

    raise ExtractionValidationError(f"Could not parse valid date from '{raw_date}'. Expected format YYYY-MM-DD or DD/MM/YYYY.")


def assemble_canonical_record(
    raw: RawExtractedTransaction,
    source_type: str,
    document_id: str,
    row_index: int,
) -> CanonicalRecord:
    """Deterministically assemble and validate a CanonicalRecord from a RawExtractedTransaction."""
    # 1. Deterministic Record ID and Source Slot
    source_upper = source_type.upper().strip()
    if source_upper not in ("GATEWAY", "BANK", "CANONICAL"):
        source_upper = "GATEWAY"

    prefix = "GTW" if source_upper == "GATEWAY" else ("BNK" if source_upper == "BANK" else "CAN")
    doc_hash = hashlib.md5(document_id.encode("utf-8")).hexdigest()[:6]
    fallback_id = f"DOC-{prefix}-{doc_hash}-{row_index:03d}"
    record_id = raw.raw_reference.strip() if (raw.raw_reference and raw.raw_reference.strip()) else fallback_id
    txn_id = record_id

    # 2. Amount and Currency Normalization
    amount, inferred_type = normalize_amount(raw.amount)
    currency = normalize_currency(raw.currency, raw.amount)

    # 3. Date Normalization
    txn_date = normalize_date(raw.transaction_date)
    settle_date = normalize_date(raw.settlement_date) if raw.settlement_date else txn_date

    # Validate timeline sanity (settlement should not precede transaction)
    if settle_date < txn_date:
        settle_date = txn_date

    # 4. Transaction Type and Status
    final_type = (
        raw.transaction_type.upper().strip()
        if raw.transaction_type
        else (inferred_type or ("CREDIT" if amount >= Decimal("0.00") else "DEBIT"))
    )
    status = "COMPLETED" if source_upper == "GATEWAY" else "POSTED"
    reference = raw.narration or raw.raw_reference or ""
    counterparty = raw.counterparty or ""

    # Optional fee
    fee_amount = None
    if raw.fee:
        try:
            f_val, _ = normalize_amount(raw.fee)
            fee_amount = abs(f_val)
        except Exception:
            fee_amount = None

    # 5. Extraction Confidence Assignment (Field-Level)
    conf = max(0.0, min(1.0, float(raw.confidence)))
    extraction_confidence = {
        "amount": conf,
        "transaction_date": conf,
        "settlement_date": conf,
        "currency": conf,
        "source_reference": conf,
        "counterparty": conf,
    }

    return CanonicalRecord(
        record_id=record_id,
        transaction_id=txn_id,
        source=source_upper,
        source_reference=reference,
        amount=amount,
        currency=currency,
        transaction_date=txn_date,
        settlement_date=settle_date,
        counterparty=counterparty,
        status=status,
        transaction_type=final_type,
        fee_amount=fee_amount,
        extraction_confidence=extraction_confidence,
    )
