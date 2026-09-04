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
                                "record_id": "SRC-ORBIT-001",
                                "reference": "ORBIT-2026-001",
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
                                "record_id": "SRC-ORBIT-002",
                                "reference": "ORBIT-2026-002",
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
                                "record_id": "BANK-ORBIT-01",
                                "reference": "ORBIT-2026-001",
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
                                "record_id": "BANK-ORBIT-02",
                                "reference": "ORBIT-2026-001",
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
                                "record_id": "BANK-DECOY-01",
                                "reference": "ORBIT-2026-001",
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
                                "record_id": "BANK-NOVA",
                                "reference": "ORBIT-2026-002",
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
        assert [t.record_id for t in txns] == expected_ids

        expected_references = [
            "ORBIT-2026-001",
            "ORBIT-2026-002",
            "ORBIT-2026-001",
            "ORBIT-2026-001",
            "ORBIT-2026-001",
            "ORBIT-2026-002",
        ]
        assert [t.raw_reference for t in txns] == expected_references

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
    
    Stage 1: Raw Model Response contains 'record_id': 'SRC-ORBIT-001', 'reference': 'ORBIT-2026-001'
    Stage 2: DocumentExtractionResult contains raw_transactions[0].record_id = 'SRC-ORBIT-001'
    Stage 3: assemble_canonical_record() preserves 'SRC-ORBIT-001' as record_id and transaction_id
    """
    raw_response_content = json.dumps({
        "transactions": [
            {
                "record_id": "SRC-ORBIT-001",
                "reference": "ORBIT-2026-001",
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
    assert raw_tx.record_id == "SRC-ORBIT-001"
    assert raw_tx.raw_reference == "ORBIT-2026-001"

    # Stage 2 -> Stage 3: assemble_canonical_record preserves exact visible ID
    canonical = assemble_canonical_record(raw_tx, source_type="GATEWAY", document_id="test_doc.png", row_index=1)
    
    assert canonical.record_id == "SRC-ORBIT-001"
    assert canonical.transaction_id == "SRC-ORBIT-001"
    assert canonical.source_reference == "ORBIT-2026-001"


def test_vision_reconciliation_end_to_end_matching():
    """Verify that records extracted from vision match correctly in reconciliation engine."""
    from eagle.reconciliation.engine import reconcile

    gtw_raw = RawExtractedTransaction(
        record_id="SRC-ORBIT-001",
        raw_reference="ORBIT-2026-001",
        transaction_date="2026-09-04",
        amount="18500",
        currency="INR",
        counterparty="Merchant-Orbit",
        narration="ORBIT-2026-001",
    )
    bnk_raw = RawExtractedTransaction(
        record_id="BANK-ORBIT-01",
        raw_reference="ORBIT-2026-001",
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
# L. Identity & Reference Separation Regression Tests (Tests 1 - 8)
# -------------------------------------------------------------------------

def test_regression_test1_distinct_record_id_and_reference_canonicalization():
    """TEST 1: Verify 4 Bank records sharing reference all survive canonicalization with distinct record_ids."""
    raw_txns = [
        RawExtractedTransaction(
            record_id="BANK-ORBIT-01",
            raw_reference="ORBIT-2026-001",
            transaction_date="2026-09-04",
            amount="11000",
            currency="INR",
            counterparty="Merchant-Orbit",
        ),
        RawExtractedTransaction(
            record_id="BANK-ORBIT-02",
            raw_reference="ORBIT-2026-001",
            transaction_date="2026-09-04",
            amount="7500",
            currency="INR",
            counterparty="Merchant-Orbit",
        ),
        RawExtractedTransaction(
            record_id="BANK-DECOY-01",
            raw_reference="ORBIT-2026-001",
            transaction_date="2026-09-04",
            amount="18500",
            currency="INR",
            counterparty="Wrong-Merchant",
        ),
        RawExtractedTransaction(
            record_id="BANK-NOVA",
            raw_reference="ORBIT-2026-002",
            transaction_date="2026-09-04",
            amount="7500",
            currency="INR",
            counterparty="Merchant-Nova",
        ),
    ]

    canonical_records = [
        assemble_canonical_record(raw, source_type="BANK", document_id="bank.png", row_index=i)
        for i, raw in enumerate(raw_txns, start=1)
    ]

    assert len(canonical_records) == 4
    assert [r.record_id for r in canonical_records] == [
        "BANK-ORBIT-01",
        "BANK-ORBIT-02",
        "BANK-DECOY-01",
        "BANK-NOVA",
    ]
    assert [r.source_reference for r in canonical_records] == [
        "ORBIT-2026-001",
        "ORBIT-2026-001",
        "ORBIT-2026-001",
        "ORBIT-2026-002",
    ]


def test_regression_test2_vision_extraction_parsing_separate_fields():
    """TEST 2: Verify parse_vision_json_response maps record_id and reference separately."""
    from eagle.extraction._nvidia_nim import parse_vision_json_response

    payload_json = json.dumps({
        "transactions": [
            {
                "record_id": "BANK-ORBIT-01",
                "reference": "ORBIT-2026-001",
                "transaction_date": "2026-09-04",
                "amount": "11000",
                "currency": "INR",
                "counterparty": "Merchant-Orbit",
            },
            {
                "record_id": "BANK-ORBIT-02",
                "reference": "ORBIT-2026-001",
                "transaction_date": "2026-09-04",
                "amount": "7500",
                "currency": "INR",
                "counterparty": "Merchant-Orbit",
            },
            {
                "record_id": "BANK-DECOY-01",
                "reference": "ORBIT-2026-001",
                "transaction_date": "2026-09-04",
                "amount": "18500",
                "currency": "INR",
                "counterparty": "Wrong-Merchant",
            },
            {
                "record_id": "BANK-NOVA",
                "reference": "ORBIT-2026-002",
                "transaction_date": "2026-09-04",
                "amount": "7500",
                "currency": "INR",
                "counterparty": "Merchant-Nova",
            },
        ]
    })

    result = parse_vision_json_response(payload_json, filename="test_bank.png")
    assert len(result.raw_transactions) == 4

    txns = result.raw_transactions
    assert [t.record_id for t in txns] == [
        "BANK-ORBIT-01",
        "BANK-ORBIT-02",
        "BANK-DECOY-01",
        "BANK-NOVA",
    ]
    assert [t.raw_reference for t in txns] == [
        "ORBIT-2026-001",
        "ORBIT-2026-001",
        "ORBIT-2026-001",
        "ORBIT-2026-002",
    ]


def test_regression_test3_full_mocked_vision_path_preserves_all_six_orbit_records():
    """TEST 3: Verify all 6 Orbit records (2 Gateway + 4 Bank) survive extraction through VisionExtractor."""
    gtw_payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "transactions": [
                            {
                                "record_id": "SRC-ORBIT-001",
                                "reference": "ORBIT-2026-001",
                                "transaction_date": "2026-09-04",
                                "amount": "18500",
                                "currency": "INR",
                                "counterparty": "Merchant-Orbit",
                            },
                            {
                                "record_id": "SRC-ORBIT-002",
                                "reference": "ORBIT-2026-002",
                                "transaction_date": "2026-09-04",
                                "amount": "7500",
                                "currency": "INR",
                                "counterparty": "Merchant-Nova",
                            },
                        ]
                    })
                }
            }
        ]
    }

    bnk_payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "transactions": [
                            {
                                "record_id": "BANK-ORBIT-01",
                                "reference": "ORBIT-2026-001",
                                "transaction_date": "2026-09-04",
                                "amount": "11000",
                                "currency": "INR",
                                "counterparty": "Merchant-Orbit",
                            },
                            {
                                "record_id": "BANK-ORBIT-02",
                                "reference": "ORBIT-2026-001",
                                "transaction_date": "2026-09-04",
                                "amount": "7500",
                                "currency": "INR",
                                "counterparty": "Merchant-Orbit",
                            },
                            {
                                "record_id": "BANK-DECOY-01",
                                "reference": "ORBIT-2026-001",
                                "transaction_date": "2026-09-04",
                                "amount": "18500",
                                "currency": "INR",
                                "counterparty": "Wrong-Merchant",
                            },
                            {
                                "record_id": "BANK-NOVA",
                                "reference": "ORBIT-2026-002",
                                "transaction_date": "2026-09-04",
                                "amount": "7500",
                                "currency": "INR",
                                "counterparty": "Merchant-Nova",
                            },
                        ]
                    })
                }
            }
        ]
    }

    extractor = VisionExtractor(provider_type="nvidia_nim", api_key="test-key")
    dummy_bytes = create_dummy_png_bytes()

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.side_effect = [
            httpx.Response(200, json=gtw_payload, request=httpx.Request("POST", "http://test")),
            httpx.Response(200, json=bnk_payload, request=httpx.Request("POST", "http://test")),
        ]

        gtw_records = asyncio.run(extractor.extract_async(dummy_bytes, source_type="GATEWAY", filename="gtw.png"))
        bnk_records = asyncio.run(extractor.extract_async(dummy_bytes, source_type="BANK", filename="bnk.png"))

        assert len(gtw_records) == 2
        assert [r.record_id for r in gtw_records] == ["SRC-ORBIT-001", "SRC-ORBIT-002"]

        assert len(bnk_records) == 4
        assert [r.record_id for r in bnk_records] == ["BANK-ORBIT-01", "BANK-ORBIT-02", "BANK-DECOY-01", "BANK-NOVA"]

        all_records = gtw_records + bnk_records
        assert len(all_records) == 6


def test_regression_test4_shared_reference_does_not_cause_deduplication():
    """TEST 4: Explicitly assert BANK-ORBIT-01, BANK-ORBIT-02, BANK-DECOY-01 remain present despite sharing reference."""
    bnk_payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "transactions": [
                            {
                                "record_id": "BANK-ORBIT-01",
                                "reference": "ORBIT-2026-001",
                                "transaction_date": "2026-09-04",
                                "amount": "11000",
                                "currency": "INR",
                                "counterparty": "Merchant-Orbit",
                            },
                            {
                                "record_id": "BANK-ORBIT-02",
                                "reference": "ORBIT-2026-001",
                                "transaction_date": "2026-09-04",
                                "amount": "7500",
                                "currency": "INR",
                                "counterparty": "Merchant-Orbit",
                            },
                            {
                                "record_id": "BANK-DECOY-01",
                                "reference": "ORBIT-2026-001",
                                "transaction_date": "2026-09-04",
                                "amount": "18500",
                                "currency": "INR",
                                "counterparty": "Wrong-Merchant",
                            },
                        ]
                    })
                }
            }
        ]
    }

    extractor = VisionExtractor(provider_type="nvidia_nim", api_key="test-key")
    dummy_bytes = create_dummy_png_bytes()

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = httpx.Response(200, json=bnk_payload, request=httpx.Request("POST", "http://test"))
        bnk_records = asyncio.run(extractor.extract_async(dummy_bytes, source_type="BANK", filename="bnk.png"))

        assert len(bnk_records) == 3
        assert [r.record_id for r in bnk_records] == ["BANK-ORBIT-01", "BANK-ORBIT-02", "BANK-DECOY-01"]
        assert all(r.source_reference == "ORBIT-2026-001" for r in bnk_records)


def test_regression_test5_missing_record_id_fallback():
    """TEST 5: If record_id is absent, fall back to deterministic DOC-* ID while preserving reference."""
    raw = RawExtractedTransaction(
        record_id=None,
        raw_reference="ORBIT-2026-001",
        transaction_date="2026-09-04",
        amount="5000",
        currency="INR",
        counterparty="Merchant-Orbit",
    )

    rec = assemble_canonical_record(raw, source_type="BANK", document_id="bank_stmt.png", row_index=3)
    assert rec.record_id.startswith("DOC-BNK-")
    assert rec.record_id != "ORBIT-2026-001"
    assert rec.transaction_id == rec.record_id
    assert rec.source_reference == "ORBIT-2026-001"


def test_regression_test6_native_csv_regression_isolation():
    """TEST 6: Native CSV records continue to parse directly into CanonicalRecords without vision/network."""
    csv_data = """payment_id,merchant_txn_ref,amount,currency,created_at,merchant_name
SRC-001,REF-001,1500.00,INR,2026-09-04,Test Merchant
SRC-002,REF-002,2500.00,INR,2026-09-04,Test Merchant 2
"""
    with patch("httpx.AsyncClient.post") as mock_post:
        records = extract_csv(csv_data, source_type="GATEWAY")
        assert len(records) == 2
        assert records[0].record_id == "SRC-001"
        assert records[0].source_reference == "REF-001"
        assert records[1].record_id == "SRC-002"
        assert records[1].source_reference == "REF-002"
        assert mock_post.call_count == 0


def test_regression_test7_orbit_dataset_end_to_end_reconciliation():
    """TEST 7 / Section 10: 2 Gateway + 4 Bank records = 6 records reach reconciliation, Nova matches at ₹7,500."""
    from eagle.reconciliation.engine import reconcile

    # Gateway records
    gtw_01 = assemble_canonical_record(
        RawExtractedTransaction(
            record_id="SRC-ORBIT-001",
            raw_reference="ORBIT-2026-001",
            amount="18500",
            currency="INR",
            transaction_date="2026-09-04",
            counterparty="Merchant-Orbit",
        ),
        source_type="GATEWAY",
        document_id="gtw.png",
        row_index=1,
    )
    gtw_02 = assemble_canonical_record(
        RawExtractedTransaction(
            record_id="SRC-ORBIT-002",
            raw_reference="ORBIT-2026-002",
            amount="7500",
            currency="INR",
            transaction_date="2026-09-04",
            counterparty="Merchant-Nova",
        ),
        source_type="GATEWAY",
        document_id="gtw.png",
        row_index=2,
    )

    # Bank records
    bnk_01 = assemble_canonical_record(
        RawExtractedTransaction(
            record_id="BANK-ORBIT-01",
            raw_reference="ORBIT-2026-001",
            amount="11000",
            currency="INR",
            transaction_date="2026-09-04",
            counterparty="Merchant-Orbit",
        ),
        source_type="BANK",
        document_id="bnk.png",
        row_index=1,
    )
    bnk_02 = assemble_canonical_record(
        RawExtractedTransaction(
            record_id="BANK-ORBIT-02",
            raw_reference="ORBIT-2026-001",
            amount="7500",
            currency="INR",
            transaction_date="2026-09-04",
            counterparty="Merchant-Orbit",
        ),
        source_type="BANK",
        document_id="bnk.png",
        row_index=2,
    )
    bnk_decoy = assemble_canonical_record(
        RawExtractedTransaction(
            record_id="BANK-DECOY-01",
            raw_reference="ORBIT-2026-001",
            amount="18500",
            currency="INR",
            transaction_date="2026-09-04",
            counterparty="Wrong-Merchant",
        ),
        source_type="BANK",
        document_id="bnk.png",
        row_index=3,
    )
    bnk_nova = assemble_canonical_record(
        RawExtractedTransaction(
            record_id="BANK-NOVA",
            raw_reference="ORBIT-2026-002",
            amount="7500",
            currency="INR",
            transaction_date="2026-09-04",
            counterparty="Merchant-Nova",
        ),
        source_type="BANK",
        document_id="bnk.png",
        row_index=4,
    )

    gtw_records = [gtw_01, gtw_02]
    bnk_records = [bnk_01, bnk_02, bnk_decoy, bnk_nova]

    assert len(gtw_records) == 2
    assert len(bnk_records) == 4

    result = reconcile(gtw_records, bnk_records)
    assert len(gtw_records) + len(bnk_records) == 6

    # Verify Nova ₹7,500 match
    nova_matches = [
        r for r in result.results
        if "SRC-ORBIT-002" in r.source_record_ids and "BANK-NOVA" in r.target_record_ids
    ]
    assert len(nova_matches) == 1
    assert nova_matches[0].outcome.value == "MATCHED"
    assert nova_matches[0].reconciled_amount == Decimal("7500")

    # Ambiguous Orbit transactions are represented in candidate pools as designed
    assert len(result.candidates) >= 1


def test_regression_test8_json_robustness_with_leading_prose():
    """TEST 8 / Section 11: Verify strip_fences and parse_vision_json_response handle introductory prose."""
    from eagle.extraction._nvidia_nim import parse_vision_json_response, strip_fences

    model_output = """Here is the extracted transaction data from the screenshot table:

```json
{
  "transactions": [
    {
      "record_id": "BANK-ORBIT-01",
      "reference": "ORBIT-2026-001",
      "transaction_date": "2026-09-04",
      "amount": "11000",
      "currency": "INR",
      "counterparty": "Merchant-Orbit"
    }
  ]
}
```

Hope this helps!"""

    stripped = strip_fences(model_output)
    assert stripped.startswith("{")
    assert stripped.endswith("}")

    result = parse_vision_json_response(model_output, filename="prose_test.png")
    assert len(result.raw_transactions) == 1
    assert result.raw_transactions[0].record_id == "BANK-ORBIT-01"
    assert result.raw_transactions[0].raw_reference == "ORBIT-2026-001"


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
