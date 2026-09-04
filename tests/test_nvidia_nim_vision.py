"""Comprehensive test suite for NVIDIA NIM multimodal vision extraction provider."""

import asyncio
import io
import json
import os
from decimal import Decimal
from unittest.mock import patch

import httpx
import pytest

from eagle.core.config import Settings
from eagle.extraction import (
    CsvExtractor,
    DocumentExtractionResult,
    ExtractionValidationError,
    ExtractorRouter,
    LlamaServerVisionProvider,
    MockVisionProvider,
    NvidiaNimVisionProvider,
    RawExtractedTransaction,
    VisionExtractor,
    assemble_canonical_record,
    extract_csv,
)
from eagle.models.canonical import CanonicalRecord


def create_dummy_png_bytes() -> bytes:
    """Create a minimal valid 10x10 PNG."""
    from PIL import Image
    buf = io.BytesIO()
    img = Image.new("RGB", (10, 10), color="white")
    img.save(buf, format="PNG")
    return buf.getvalue()


# -------------------------------------------------------------------------
# A-C. NVIDIA NIM Successful Extraction & Visible ID Preservation
# -------------------------------------------------------------------------

ORBIT_MOCK_PAYLOAD = {
    "choices": [
        {
            "message": {
                "content": json.dumps(
                    {
                        "transactions": [
                            {
                                "raw_reference": "SRC-ORBIT-001",
                                "transaction_date": "2026-09-04",
                                "settlement_date": "2026-09-04",
                                "amount": "18500",
                                "currency": "INR",
                                "counterparty": "Merchant-Orbit",
                                "narration": "ORBIT-2026-001",
                                "transaction_type": "PAYMENT",
                                "confidence": 0.98,
                            },
                            {
                                "raw_reference": "SRC-ORBIT-002",
                                "transaction_date": "2026-09-04",
                                "settlement_date": "2026-09-04",
                                "amount": "7500",
                                "currency": "INR",
                                "counterparty": "Merchant-Nova",
                                "narration": "ORBIT-2026-002",
                                "transaction_type": "PAYMENT",
                                "confidence": 0.95,
                            },
                            {
                                "raw_reference": "BANK-ORBIT-01",
                                "transaction_date": "2026-09-04",
                                "settlement_date": "2026-09-04",
                                "amount": "11000",
                                "currency": "INR",
                                "counterparty": "Merchant-Orbit",
                                "narration": "ORBIT-2026-001",
                                "transaction_type": "CREDIT",
                                "confidence": 0.96,
                            },
                            {
                                "raw_reference": "BANK-ORBIT-02",
                                "transaction_date": "2026-09-04",
                                "settlement_date": "2026-09-04",
                                "amount": "7500",
                                "currency": "INR",
                                "counterparty": "Merchant-Orbit",
                                "narration": "ORBIT-2026-001",
                                "transaction_type": "CREDIT",
                                "confidence": 0.94,
                            },
                            {
                                "raw_reference": "BANK-DECOY-01",
                                "transaction_date": "2026-09-04",
                                "settlement_date": "2026-09-04",
                                "amount": "18500",
                                "currency": "INR",
                                "counterparty": "Wrong-Merchant",
                                "narration": "ORBIT-2026-001",
                                "transaction_type": "CREDIT",
                                "confidence": 0.92,
                            },
                            {
                                "raw_reference": "BANK-NOVA",
                                "transaction_date": "2026-09-04",
                                "settlement_date": "2026-09-04",
                                "amount": "7500",
                                "currency": "INR",
                                "counterparty": "Merchant-Nova",
                                "narration": "ORBIT-2026-002",
                                "transaction_type": "CREDIT",
                                "confidence": 0.97,
                            },
                        ]
                    }
                )
            }
        }
    ]
}


def test_nvidia_nim_successful_extraction_and_payload_format():
    """Verify NVIDIA NIM provider constructs valid multimodal payload and parses records."""
    png_bytes = create_dummy_png_bytes()
    provider = NvidiaNimVisionProvider(
        api_key="test-nv-key-12345",
        base_url="https://integrate.api.nvidia.com/v1",
        model="meta/llama-3.2-11b-vision-instruct",
        timeout=45,
    )

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = httpx.Response(
            200,
            json=ORBIT_MOCK_PAYLOAD,
            request=httpx.Request("POST", "https://integrate.api.nvidia.com/v1/chat/completions"),
        )

        res = asyncio.run(provider.extract_transactions_async(png_bytes, filename="orbit_table.png"))

        assert res.filename == "orbit_table.png"
        assert res.extraction_method == "NVIDIA_NIM_VISION"
        assert len(res.raw_transactions) == 6

        # Check call arguments and headers
        call_args, call_kwargs = mock_post.call_args
        assert call_args[0] == "https://integrate.api.nvidia.com/v1/chat/completions"
        assert call_kwargs["headers"]["Authorization"] == "Bearer test-nv-key-12345"
        assert call_kwargs["headers"]["Content-Type"] == "application/json"

        # Check multimodal request payload: instructions in user message with image_url
        sent_json = call_kwargs["json"]
        assert sent_json["model"] == "meta/llama-3.2-11b-vision-instruct"
        assert len(sent_json["messages"]) == 1
        user_msg = sent_json["messages"][0]
        assert user_msg["role"] == "user"
        assert user_msg["content"][0]["type"] == "text"
        assert "financial transaction" in user_msg["content"][0]["text"].lower()
        assert user_msg["content"][1]["type"] == "image_url"
        assert user_msg["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_nvidia_nim_exact_visible_id_and_cell_preservation():
    """Verify all 6 synthetic Orbit table records preserve visible IDs, amounts, counterparties."""
    png_bytes = create_dummy_png_bytes()
    provider = NvidiaNimVisionProvider(api_key="dummy-key")

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = httpx.Response(
            200,
            json=ORBIT_MOCK_PAYLOAD,
            request=httpx.Request("POST", "https://integrate.api.nvidia.com/v1/chat/completions"),
        )

        res = asyncio.run(provider.extract_transactions_async(png_bytes, filename="orbit.png"))
        txns = res.raw_transactions
        assert len(txns) == 6

        expected_ids = [
            "SRC-ORBIT-001",
            "SRC-ORBIT-002",
            "BANK-ORBIT-01",
            "BANK-ORBIT-02",
            "BANK-DECOY-01",
            "BANK-NOVA",
        ]
        assert [t.raw_reference for t in txns] == expected_ids

        expected_amounts = ["18500", "7500", "11000", "7500", "18500", "7500"]
        assert [t.amount for t in txns] == expected_amounts

        expected_counterparties = [
            "Merchant-Orbit",
            "Merchant-Nova",
            "Merchant-Orbit",
            "Merchant-Orbit",
            "Wrong-Merchant",
            "Merchant-Nova",
        ]
        assert [t.counterparty for t in txns] == expected_counterparties


# -------------------------------------------------------------------------
# D-H. Error Handling & Validation Tests
# -------------------------------------------------------------------------

def test_nvidia_nim_missing_api_key():
    """Verify missing API key raises clear ExtractionValidationError without network call."""
    provider = NvidiaNimVisionProvider(api_key="")
    png_bytes = create_dummy_png_bytes()

    with pytest.raises(ExtractionValidationError, match="NVIDIA NIM API key is missing"):
        asyncio.run(provider.extract_transactions_async(png_bytes, filename="test.png"))


def test_nvidia_nim_malformed_model_json():
    """Verify malformed JSON from model raises ExtractionValidationError."""
    provider = NvidiaNimVisionProvider(api_key="valid-key")
    png_bytes = create_dummy_png_bytes()

    mock_resp = {
        "choices": [
            {
                "message": {
                    "content": "Here is your JSON: { transactions: [ NOT VALID JSON ] }"
                }
            }
        ]
    }

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = httpx.Response(
            200,
            json=mock_resp,
            request=httpx.Request("POST", "https://integrate.api.nvidia.com/v1/chat/completions"),
        )
        with pytest.raises(ExtractionValidationError, match="Malformed JSON"):
            asyncio.run(provider.extract_transactions_async(png_bytes, filename="test.png"))


def test_nvidia_nim_http_4xx_error():
    """Verify HTTP 4xx error raises clean ExtractionValidationError and does not leak secrets."""
    secret_key = "super-secret-nv-key-999"
    provider = NvidiaNimVisionProvider(api_key=secret_key)
    png_bytes = create_dummy_png_bytes()

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = httpx.Response(
            401,
            text="Unauthorized: Invalid API Key",
            request=httpx.Request("POST", "https://integrate.api.nvidia.com/v1/chat/completions"),
        )
        with pytest.raises(ExtractionValidationError) as exc_info:
            asyncio.run(provider.extract_transactions_async(png_bytes, filename="test.png"))

        err_msg = str(exc_info.value)
        assert "NVIDIA NIM returned HTTP 401" in err_msg
        assert secret_key not in err_msg


def test_nvidia_nim_http_5xx_error():
    """Verify HTTP 5xx server error raises clean ExtractionValidationError."""
    provider = NvidiaNimVisionProvider(api_key="valid-key")
    png_bytes = create_dummy_png_bytes()

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = httpx.Response(
            503,
            text="Service Unavailable: Model overloaded",
            request=httpx.Request("POST", "https://integrate.api.nvidia.com/v1/chat/completions"),
        )
        with pytest.raises(ExtractionValidationError, match="NVIDIA NIM returned HTTP 503"):
            asyncio.run(provider.extract_transactions_async(png_bytes, filename="test.png"))


def test_nvidia_nim_timeout():
    """Verify request timeout raises clean ExtractionValidationError."""
    provider = NvidiaNimVisionProvider(api_key="valid-key", timeout=10)
    png_bytes = create_dummy_png_bytes()

    with patch("httpx.AsyncClient.post", side_effect=httpx.TimeoutException("Read timed out")):
        with pytest.raises(ExtractionValidationError, match="timed out after 10s"):
            asyncio.run(provider.extract_transactions_async(png_bytes, filename="test.png"))


# -------------------------------------------------------------------------
# I. Provider Dispatch & Independence
# -------------------------------------------------------------------------

def test_vision_provider_selection_dispatch():
    """Verify VisionExtractor instantiates appropriate provider based on provider_type."""
    # 1. NVIDIA NIM selection
    vis_nv = VisionExtractor(provider_type="nvidia_nim", api_key="test-key")
    assert isinstance(vis_nv.provider, NvidiaNimVisionProvider)
    assert vis_nv.provider.model == "meta/llama-3.2-11b-vision-instruct"

    # 2. llama-server selection
    vis_llama = VisionExtractor(provider_type="llama_server", base_url="http://127.0.0.1:8080")
    assert isinstance(vis_llama.provider, LlamaServerVisionProvider)
    assert vis_llama.provider.base_url == "http://127.0.0.1:8080"

    # 3. mock selection
    vis_mock = VisionExtractor(provider_type="mock")
    assert isinstance(vis_mock.provider, MockVisionProvider)


def test_unknown_vision_provider_raises_error():
    """Verify invalid vision provider type raises ExtractionValidationError."""
    vis = VisionExtractor(provider_type="invalid_provider")
    with pytest.raises(ExtractionValidationError, match="Unknown vision provider"):
        _ = vis.provider


# -------------------------------------------------------------------------
# J. CSV Isolation: CSV ingestion never calls NVIDIA NIM
# -------------------------------------------------------------------------

def test_csv_extraction_does_not_invoke_nvidia_or_network():
    """Verify native CSV extraction executes without any network calls or vision provider access."""
    csv_data = """payment_id,merchant_txn_ref,amount,currency,created_at,merchant_name
SRC-001,REF-001,1500.00,INR,2026-09-04,Test Merchant
"""
    with patch("httpx.AsyncClient.post") as mock_post:
        records = extract_csv(csv_data, source_type="GATEWAY")
        assert len(records) == 1
        assert records[0].record_id == "SRC-001"
        assert records[0].amount == Decimal("1500.00")
        assert mock_post.call_count == 0


def test_extractor_router_routes_csv_natively_without_vision():
    """Verify ExtractorRouter routes CSV directly without touching vision extractor."""
    router = ExtractorRouter()
    csv_data = b"payment_id,amount,created_at\nSRC-01,500.00,2026-09-04"

    with patch("httpx.AsyncClient.post") as mock_post:
        records = router.extract(csv_data, filename="transactions.csv")
        assert len(records) == 1
        assert records[0].record_id == "SRC-01"
        assert mock_post.call_count == 0


# -------------------------------------------------------------------------
# K. End-to-End Mocked Vision Extraction -> Canonical Assembly & ID Lifecycle Diagnostic
# -------------------------------------------------------------------------

def test_end_to_end_nvidia_nim_vision_extraction_to_canonical_records():
    """Verify image bytes flow through NvidiaNimVisionProvider into CanonicalRecord assembly."""
    png_bytes = create_dummy_png_bytes()
    extractor = VisionExtractor(provider_type="nvidia_nim", api_key="valid-key")

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = httpx.Response(
            200,
            json=ORBIT_MOCK_PAYLOAD,
            request=httpx.Request("POST", "https://integrate.api.nvidia.com/v1/chat/completions"),
        )

        canonical_records = asyncio.run(
            extractor.extract_async(png_bytes, source_type="GATEWAY", filename="orbit_export.png")
        )

        assert len(canonical_records) == 6
        assert all(isinstance(r, CanonicalRecord) for r in canonical_records)

        # Check first record properties
        rec0 = canonical_records[0]
        assert rec0.source == "GATEWAY"
        assert rec0.amount == Decimal("18500")
        assert rec0.currency == "INR"
        assert rec0.record_id == "SRC-ORBIT-001"
        assert rec0.transaction_id == "SRC-ORBIT-001"
        assert rec0.counterparty == "Merchant-Orbit"
        assert rec0.source_reference == "ORBIT-2026-001"
        assert rec0.extraction_confidence["amount"] == 0.98

        expected_ids = [
            "SRC-ORBIT-001",
            "SRC-ORBIT-002",
            "BANK-ORBIT-01",
            "BANK-ORBIT-02",
            "BANK-DECOY-01",
            "BANK-NOVA",
        ]
        assert [r.record_id for r in canonical_records] == expected_ids


def test_diagnostic_id_lifecycle_tracing():
    """Diagnostic test tracing exact stage where source record ID is transformed.
    
    Stage 1: Raw Model Response contains 'raw_reference': 'SRC-ORBIT-001'
    Stage 2: DocumentExtractionResult contains raw_transactions[0].raw_reference = 'SRC-ORBIT-001'
    Stage 3: assemble_canonical_record() preserves 'SRC-ORBIT-001' as record_id and transaction_id
    """
    raw_response_content = json.dumps({
        "transactions": [
            {
                "raw_reference": "SRC-ORBIT-001",
                "transaction_date": "2026-09-04",
                "amount": "18500",
                "currency": "INR",
                "counterparty": "Merchant-Orbit",
                "narration": "ORBIT-2026-001",
            }
        ]
    })

    # Stage 1 -> Stage 2: JSON to DocumentExtractionResult
    from eagle.extraction._nvidia_nim import parse_vision_json_response
    extraction_result = parse_vision_json_response(raw_response_content, filename="test_doc.png")
    assert len(extraction_result.raw_transactions) == 1
    raw_tx = extraction_result.raw_transactions[0]
    assert raw_tx.raw_reference == "SRC-ORBIT-001"

    # Stage 2 -> Stage 3: assemble_canonical_record preserves exact visible ID
    canonical = assemble_canonical_record(raw_tx, source_type="GATEWAY", document_id="test_doc.png", row_index=1)
    
    assert canonical.record_id == "SRC-ORBIT-001"
    assert canonical.transaction_id == "SRC-ORBIT-001"
    assert canonical.source_reference == "ORBIT-2026-001"


def test_vision_reconciliation_end_to_end_matching():
    """Verify that records extracted from vision match correctly in reconciliation engine."""
    from eagle.reconciliation.engine import reconcile

    gtw_raw = RawExtractedTransaction(
        raw_reference="SRC-ORBIT-001",
        transaction_date="2026-09-04",
        amount="18500",
        currency="INR",
        counterparty="Merchant-Orbit",
        narration="ORBIT-2026-001",
    )
    bnk_raw = RawExtractedTransaction(
        raw_reference="BANK-ORBIT-01",
        transaction_date="2026-09-04",
        amount="18500",
        currency="INR",
        counterparty="Merchant-Orbit",
        narration="ORBIT-2026-001",
    )

    gtw_rec = assemble_canonical_record(gtw_raw, source_type="GATEWAY", document_id="gtw.png", row_index=1)
    bnk_rec = assemble_canonical_record(bnk_raw, source_type="BANK", document_id="bnk.png", row_index=1)

    res = reconcile([gtw_rec], [bnk_rec])
    assert len(res.results) == 1
    rel = res.results[0]
    assert rel.source_record_ids == ["SRC-ORBIT-001"]
    assert rel.target_record_ids == ["BANK-ORBIT-01"]
    assert rel.outcome.value == "MATCHED"
    assert rel.reconciled_amount == Decimal("18500")


# -------------------------------------------------------------------------
# Optional Live NVIDIA NIM Test (Disabled by default)
# -------------------------------------------------------------------------

@pytest.mark.skipif(
    not os.getenv("RUN_NVIDIA_LIVE_TEST"),
    reason="Live NVIDIA NIM integration test disabled by default (requires RUN_NVIDIA_LIVE_TEST=1 and NVIDIA_NIM_API_KEY)",
)
def test_live_nvidia_nim_extraction():
    """Optional live test validating NVIDIA NIM vision extraction against live API."""
    api_key = os.getenv("NVIDIA_NIM_API_KEY", "")
    assert api_key, "NVIDIA_NIM_API_KEY must be set to run live test."

    extractor = VisionExtractor(provider_type="nvidia_nim", api_key=api_key)
    png_bytes = create_dummy_png_bytes()

    res = asyncio.run(extractor.extract_preview_async(png_bytes, filename="live_test.png"))
    assert res.extraction_method == "NVIDIA_NIM_VISION"
