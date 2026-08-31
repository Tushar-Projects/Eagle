"""Comprehensive test suite for vision, hybrid PDF, and document extraction pipeline."""

import asyncio
import io
import json
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import httpx
import pypdf
import pytest
from fastapi.testclient import TestClient

from eagle.api.main import app
from eagle.api.routes import get_service
from eagle.extraction import (
    CsvExtractor,
    DocumentExtractionResult,
    ExtractionValidationError,
    ExtractorRouter,
    JsonExtractor,
    MockVisionProvider,
    PdfExtractor,
    RawExtractedTransaction,
    VisionExtractor,
    assemble_canonical_record,
    normalize_amount,
    normalize_currency,
    normalize_date,
)
from eagle.extraction.normalizer import is_non_transaction_row
from eagle.models.canonical import CanonicalRecord
from eagle.services.reconciliation_service import ReconciliationService
from eagle.storage.database import Database
from eagle.storage.repository import Repository


# -------------------------------------------------------------------------
# Test Fixtures & In-Memory Helpers
# -------------------------------------------------------------------------

@pytest.fixture
def test_repo():
    db = Database(":memory:")
    return Repository(db)


@pytest.fixture
def mock_service(test_repo):
    from eagle.agents._mock import MockProvider
    return ReconciliationService(
        repository=test_repo,
        provider=MockProvider(),
    )


def create_dummy_png_bytes() -> bytes:
    """Create a minimal valid 1x1 PNG."""
    from PIL import Image
    buf = io.BytesIO()
    img = Image.new("RGB", (10, 10), color="white")
    img.save(buf, format="PNG")
    return buf.getvalue()


def create_dummy_jpeg_bytes() -> bytes:
    """Create a minimal valid JPEG."""
    from PIL import Image
    buf = io.BytesIO()
    img = Image.new("RGB", (10, 10), color="white")
    img.save(buf, format="JPEG")
    return buf.getvalue()


def create_digital_pdf_bytes(lines: list[str]) -> bytes:
    """Create an in-memory PDF."""
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=300, height=400)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


# -------------------------------------------------------------------------
# 1-3. Vision Payload Construction & Base64 Encoding
# -------------------------------------------------------------------------

def test_png_extraction_payload_and_base64():
    png_bytes = create_dummy_png_bytes()
    extractor = VisionExtractor(base_url="http://127.0.0.1:8000", provider_type="llama_server")

    mock_resp = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "transactions": [
                                {
                                    "raw_reference": "TXN-PNG-1",
                                    "transaction_date": "2025-01-10",
                                    "amount": "1500.00",
                                    "currency": "INR",
                                    "counterparty": "Test Merchant",
                                    "confidence": 0.95,
                                }
                            ]
                        }
                    )
                }
            }
        ]
    }

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = httpx.Response(
            200,
            json=mock_resp,
            request=httpx.Request("POST", "http://127.0.0.1:8000/v1/chat/completions"),
        )

        res = asyncio.run(extractor.extract_preview_async(png_bytes, filename="receipt.png"))
        assert res.page_count == 1
        assert len(res.raw_transactions) == 1
        assert res.raw_transactions[0].raw_reference == "TXN-PNG-1"
        assert res.raw_transactions[0].amount == "1500.00"

        # Verify payload sent to llama-server
        call_kwargs = mock_post.call_args[1]
        sent_json = call_kwargs["json"]
        assert sent_json["response_format"] == {"type": "json_object"}
        user_msg = sent_json["messages"][1]["content"]
        assert user_msg[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_jpeg_extraction_payload_and_base64():
    jpeg_bytes = create_dummy_jpeg_bytes()
    extractor = VisionExtractor(base_url="http://127.0.0.1:8000", provider_type="llama_server")

    mock_resp = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "transactions": [
                                {
                                    "raw_reference": "TXN-JPEG-1",
                                    "transaction_date": "2025-01-11",
                                    "amount": "3200.00",
                                    "currency": "USD",
                                    "confidence": 0.90,
                                }
                            ]
                        }
                    )
                }
            }
        ]
    }

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = httpx.Response(
            200,
            json=mock_resp,
            request=httpx.Request("POST", "http://127.0.0.1:8000/v1/chat/completions"),
        )

        res = asyncio.run(extractor.extract_preview_async(jpeg_bytes, filename="invoice.jpg"))
        assert len(res.raw_transactions) == 1
        assert res.raw_transactions[0].currency == "USD"

        sent_json = mock_post.call_args[1]["json"]
        user_msg = sent_json["messages"][1]["content"]
        assert user_msg[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


# -------------------------------------------------------------------------
# 4-6. Structured & Fenced JSON Parsing and Malformed Rejection
# -------------------------------------------------------------------------

def test_structured_and_fenced_json_parsing():
    extractor = VisionExtractor()

    # Plain JSON
    raw_json = json.dumps({"transactions": [{"transaction_date": "2025-01-15", "amount": "500.00"}]})
    res1 = extractor._parse_vision_response(raw_json, "test.png")
    assert len(res1.raw_transactions) == 1

    # Fenced JSON with markdown ```json ... ```
    fenced_json = f"```json\n{raw_json}\n```"
    res2 = extractor._parse_vision_response(fenced_json, "test.png")
    assert len(res2.raw_transactions) == 1


def test_malformed_json_rejection():
    extractor = VisionExtractor()
    with pytest.raises(ExtractionValidationError, match="Malformed JSON"):
        extractor._parse_vision_response("INVALID_NOT_JSON", "test.png")


# -------------------------------------------------------------------------
# 7-11. Financial Normalization (Amount, Dates, Currencies, CR/DR, Parentheses)
# -------------------------------------------------------------------------

def test_amount_normalization_inr_notation():
    val, _ = normalize_amount("₹ 1,25,000.50")
    assert val == Decimal("125000.50")


def test_amount_normalization_usd_and_commas():
    val, _ = normalize_amount("$1,500.00")
    assert val == Decimal("1500.00")


def test_amount_normalization_cr_dr_suffixes():
    val_cr, typ_cr = normalize_amount("5000.00 CR")
    assert val_cr == Decimal("5000.00")
    assert typ_cr == "CREDIT"

    val_dr, typ_dr = normalize_amount("250.00 DR")
    assert val_dr == Decimal("250.00")
    assert typ_dr == "DEBIT"


def test_amount_normalization_accounting_parentheses():
    val, typ = normalize_amount("(450.00)")
    assert val == Decimal("-450.00")
    assert typ == "DEBIT"


def test_invalid_amount_rejection():
    with pytest.raises(ExtractionValidationError):
        normalize_amount("abc.xyz")

    with pytest.raises(ExtractionValidationError):
        normalize_amount("")


def test_date_normalization_formats():
    assert normalize_date("2025-01-15") == date(2025, 1, 15)
    assert normalize_date("15/01/2025") == date(2025, 1, 15)
    assert normalize_date("15-01-2025") == date(2025, 1, 15)
    assert normalize_date("15-Jan-2025") == date(2025, 1, 15)
    assert normalize_date("15 January 2025") == date(2025, 1, 15)


def test_invalid_date_rejection():
    with pytest.raises(ExtractionValidationError):
        normalize_date("not-a-date")


def test_currency_normalization():
    assert normalize_currency("₹") == "INR"
    assert normalize_currency("Rs.") == "INR"
    assert normalize_currency("$") == "USD"
    assert normalize_currency("€") == "EUR"
    assert normalize_currency("EUR") == "EUR"
    assert normalize_currency("GBP") == "GBP"


# -------------------------------------------------------------------------
# 12-15. Non-Transaction Row Filtering (Balances, Subtotals, Headers)
# -------------------------------------------------------------------------

def test_non_transaction_filtering():
    assert is_non_transaction_row("Opening Balance 25000.00") is True
    assert is_non_transaction_row("Closing Balance: 35,000.00") is True
    assert is_non_transaction_row("Balance B/F 12000.00") is True
    assert is_non_transaction_row("Total 50,000.00") is True
    assert is_non_transaction_row("Page Total") is True
    assert is_non_transaction_row("Grand Total: 100000.00") is True
    assert is_non_transaction_row("Date Particulars Withdrawal Deposit Balance") is True
    assert is_non_transaction_row("Payment ID Merchant Reference Amount Status") is True

    # Legitimate transactions must NOT be filtered
    assert is_non_transaction_row("Payment to Acme Supplies Ltd") is False
    assert is_non_transaction_row("TXN-1002 Settlement from Gateway") is False


# -------------------------------------------------------------------------
# 16-19. Hybrid PDF & Multi-Page Deduplication
# -------------------------------------------------------------------------

def test_pdf_line_parsing():
    extractor = PdfExtractor()
    line = "2025-01-15 PAY-9988 ACME_CORP 5000.00"
    tx = extractor._parse_text_line_to_transaction(line)
    assert tx is not None
    assert tx.transaction_date == "2025-01-15"
    assert tx.amount == "5000.00"
    assert tx.raw_reference == "PAY-9988"


def test_pdf_multi_page_carry_over_deduplication():
    extractor = PdfExtractor()
    tx1 = RawExtractedTransaction(
        raw_reference="PAY-1", transaction_date="2025-01-15", amount="1000.00", narration="Tx 1"
    )
    tx2 = RawExtractedTransaction(
        raw_reference="PAY-2", transaction_date="2025-01-15", amount="2000.00", narration="Tx 2"
    )
    # tx2 repeated on page 2 boundary
    tx2_dup = RawExtractedTransaction(
        raw_reference="PAY-2", transaction_date="2025-01-15", amount="2000.00", narration="Tx 2"
    )
    tx3 = RawExtractedTransaction(
        raw_reference="PAY-3", transaction_date="2025-01-16", amount="3000.00", narration="Tx 3"
    )

    deduped = extractor._deduplicate_rows([tx1, tx2, tx2_dup, tx3])
    assert len(deduped) == 3
    assert [t.raw_reference for t in deduped] == ["PAY-1", "PAY-2", "PAY-3"]


def test_scanned_pdf_vision_fallback():
    pdf_bytes = create_digital_pdf_bytes([])
    mock_vis = MockVisionProvider([
        RawExtractedTransaction(
            raw_reference="SCANNED-01",
            transaction_date="2025-01-12",
            amount="7500.00",
            currency="INR",
            confidence=0.92,
        )
    ])
    extractor = PdfExtractor(vision_extractor=VisionExtractor(provider_type="mock"))
    extractor._vision_extractor._mock_provider = mock_vis

    res = asyncio.run(extractor.extract_preview_async(pdf_bytes, filename="scanned.pdf"))
    assert res.extraction_method == "SCANNED_PDF_VISION"
    assert len(res.raw_transactions) == 1
    assert res.raw_transactions[0].raw_reference == "SCANNED-01"


# -------------------------------------------------------------------------
# 20-23. Deterministic Record ID, Source Assignment & Confidence
# -------------------------------------------------------------------------

def test_deterministic_record_id_and_source_assignment():
    raw = RawExtractedTransaction(
        raw_reference="TXN-101",
        transaction_date="2025-01-15",
        settlement_date="2025-01-16",
        amount="1250.00",
        currency="INR",
        counterparty="Merchant A",
        confidence=0.88,
    )

    # Gateway assignment
    gtw_rec = assemble_canonical_record(raw, source_type="GATEWAY", document_id="doc123.pdf", row_index=1)
    assert gtw_rec.source == "GATEWAY"
    assert gtw_rec.record_id.startswith("DOC-GTW-")
    assert gtw_rec.amount == Decimal("1250.00")
    assert gtw_rec.extraction_confidence["amount"] == 0.88
    assert gtw_rec.extraction_confidence["transaction_date"] == 0.88

    # Bank assignment
    bnk_rec = assemble_canonical_record(raw, source_type="BANK", document_id="doc123.pdf", row_index=2)
    assert bnk_rec.source == "BANK"
    assert bnk_rec.record_id.startswith("DOC-BNK-")


def test_low_confidence_propagation():
    raw_low = RawExtractedTransaction(
        raw_reference="LOW-01",
        transaction_date="2025-01-15",
        amount="500.00",
        currency="INR",
        confidence=0.60,  # low confidence (< 0.75)
    )
    rec = assemble_canonical_record(raw_low, source_type="GATEWAY", document_id="scan.png", row_index=1)
    assert rec.extraction_confidence["amount"] == 0.60
    assert rec.extraction_confidence["amount"] < 0.75


# -------------------------------------------------------------------------
# 24-25. ExtractorRouter Format Detection & Error Handling
# -------------------------------------------------------------------------

def test_router_format_detection():
    router = ExtractorRouter()

    assert router.detect_format(b"%PDF-1.4...", filename="statement.pdf") == "PDF"
    assert router.detect_format(b"\x89PNG\r\n\x1a\n...", filename="receipt.png") == "IMAGE"
    assert router.detect_format(b"\xff\xd8\xff...", filename="photo.jpg") == "IMAGE"
    assert router.detect_format(b'{"records": []}', filename="data.json") == "JSON"
    assert router.detect_format(b"payment_id,amount,date\n", filename="gateway.csv") == "CSV"


def test_llama_server_unavailable_behavior():
    extractor = VisionExtractor(base_url="http://127.0.0.1:9999", timeout=1, provider_type="llama_server")
    png_bytes = create_dummy_png_bytes()

    with patch("httpx.AsyncClient.post", side_effect=Exception("Connection refused")):
        with pytest.raises(ExtractionValidationError, match="Failed to communicate with llama-server"):
            asyncio.run(extractor.extract_preview_async(png_bytes, filename="test.png"))


# -------------------------------------------------------------------------
# 26-28. API Preview Endpoint & End-to-End Ingestion
# -------------------------------------------------------------------------

def test_extract_preview_endpoint(mock_service):
    app.dependency_overrides[get_service] = lambda: mock_service
    client = TestClient(app)
    csv_content = "payment_id,amount,created_at,merchant_txn_ref\nPAY-99,500.00,2025-01-15,REF-99\n"

    response = client.post(
        "/runs/extract-preview?source_type=GATEWAY",
        files={"file": ("gateway.csv", csv_content.encode("utf-8"), "text/csv")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["file_type"] == "CSV"
    assert len(data["raw_transactions"]) == 1
    assert data["raw_transactions"][0]["amount"] == "500.00"


def test_end_to_end_image_and_mixed_csv_pdf_ingestion(mock_service):
    # Test mixed ingestion: Gateway CSV + Bank Mock Image
    gtw_csv = "payment_id,amount,created_at,merchant_txn_ref\nPAY-101,2500.00,2025-01-15,REF-101\n"
    bank_png = create_dummy_png_bytes()

    # Set router vision extractor to mock mode
    mock_service.router.vision_extractor._provider_type = "mock"
    mock_service.router.pdf_extractor._vision_extractor._provider_type = "mock"

    res = asyncio.run(
        mock_service.reconcile_files_async(
            gateway_input=gtw_csv.encode("utf-8"),
            bank_input=bank_png,
            gateway_filename="gateway.csv",
            bank_filename="bank_statement.png",
        )
    )

    assert "summary" in res
    assert res["summary"]["source_count"] == 1
    assert res["summary"]["target_count"] == 2
    assert res["summary"]["status"] == "COMPLETED"
